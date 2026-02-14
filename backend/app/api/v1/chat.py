"""聊天API（流式输出）.

Review note:
- 多轮论文上下文状态放在 conversations.extra（registry + active_ids）。
- assistant 的检索轨迹放在 messages.extra，便于回放与排障。
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator, Optional, Dict
import asyncio
import json
import logging

from app.database import get_session, get_chat_session
from app.crud.conversation import conversation_crud, message_crud
from app.crud.tool import tool_crud
from app.schemas.chat import ChatRequest, StopChatRequest
from app.utils.openai_helper import stream_chat_completion
from app.utils.chat2api_helper import stream_chat2api_completion
from app.utils.pricing import compute_text_cost
from app.utils.system_prompt import get_default_system_prompt, pick_system_prompt
from app.config import settings
from app.services.pipeline.paper_pipeline import ArxivPipelineError, build_arxiv_context_for_targets
from app.services.sources.arxiv.id_parser import extract_arxiv_targets, build_target_from_ids
from app.services.session.paper_state import (
    activate_papers_in_conversation,
    get_active_registry_entries,
    parse_conversation_extra,
    serialize_conversation_extra,
    upsert_registry_entries,
)

router = APIRouter()
logger = logging.getLogger("uvicorn.error")

# 全局字典存储正在进行的流式请求（用于停止功能）
active_streams = {}



def get_message_content(msg, selected_versions: Optional[Dict[str, int]] = None) -> str:
    """
    获取消息的显示内容，考虑选中的版本
    
    Args:
        msg: 消息对象
        selected_versions: 消息ID到版本索引的映射
    
    Returns:
        消息内容
    """
    if msg.role == 'assistant' and msg.retry_versions and selected_versions and msg.id in selected_versions:
        version_idx = selected_versions[msg.id]
        try:
            retry_versions = json.loads(msg.retry_versions) if isinstance(msg.retry_versions, str) else msg.retry_versions
            if version_idx > 0 and version_idx <= len(retry_versions):
                return retry_versions[version_idx - 1]
        except:
            pass
    return msg.content


async def generate_chat_stream(
    conversation_id: str,
    tool_id: str,
    user_message: str,
    user_images: list,
    api_config,
    chat_db: AsyncSession,
    tools_db: AsyncSession,
    retry_message_id: str = None,
    selected_versions: Optional[Dict[str, int]] = None,
    context_rounds: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    """生成聊天流式响应"""

    # 保证 finally 中引用的状态总是已定义，避免早退分支触发 UnboundLocalError。
    full_response = ""
    thinking_response = ""
    usage_data: Optional[Dict] = None
    stopped_by_user = False
    cancelled = False
    assistant_saved = False
    assistant_msg = None

    try:
        # 1. 获取system prompt
        # 如果指定了tool_id，使用 tools_db 获取工具的system prompt
        # 否则使用默认的system prompt
        if tool_id:
            tool = await tool_crud.get(tools_db, tool_id)
            if not tool:
                error_data = json.dumps({"error": "工具不存在"})
                yield f"event: error\ndata: {error_data}\n\n"
                return
            system_prompt = tool.system_prompt
        else:
            system_prompt = None
        
        # 2. 使用 chat_db 获取会话历史消息
        messages_history = await message_crud.get_by_conversation(chat_db, conversation_id)
        if retry_message_id:
            trimmed = []
            for msg in messages_history:
                if msg.id == retry_message_id:
                    break
                trimmed.append(msg)
            messages_history = trimmed
            # 编辑重试：将目标 assistant 前最近一条 user 消息更新为本次请求内容。
            # 这样可复用重试链路，同时确保 LLM 与数据库都使用新 user 内容。
            retry_user_msg = None
            for i in range(len(messages_history) - 1, -1, -1):
                if messages_history[i].role == "user":
                    retry_user_msg = messages_history[i]
                    break
            if retry_user_msg:
                retry_user_msg.content = user_message
                retry_user_msg.images = json.dumps(user_images) if user_images else None
                await message_crud.update(chat_db, retry_user_msg.id, retry_user_msg)
        # 通用对话：从历史 system 消息取系统提示词
        if not tool_id:
            system_prompt = pick_system_prompt(messages_history)
        if not system_prompt:
            system_prompt = get_default_system_prompt()

        # 过滤 system 消息（避免重复传入）
        messages_history = [m for m in messages_history if m.role != "system"]

        if context_rounds is not None:
            # 保留最近N轮（以用户消息为轮次起点）
            if context_rounds <= 0:
                if retry_message_id:
                    # 重试时至少保留最近一条用户消息作为提示
                    last_user_idx = None
                    for i in range(len(messages_history) - 1, -1, -1):
                        if messages_history[i].role == "user":
                            last_user_idx = i
                            break
                    messages_history = messages_history[last_user_idx:] if last_user_idx is not None else []
                else:
                    messages_history = []
            else:
                user_indices = [i for i, msg in enumerate(messages_history) if msg.role == "user"]
                if len(user_indices) > context_rounds:
                    start_idx = user_indices[-context_rounds]
                    messages_history = messages_history[start_idx:]
        
        # 4. 构建OpenAI消息格式
        openai_messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # 添加历史消息
        for msg in messages_history:
            if msg.role in ["user", "assistant"]:
                if msg.role == "user" and msg.images:
                    # 用户消息带图片
                    content_parts = [{"type": "text", "text": msg.content}] if msg.content else []
                    try:
                        images = json.loads(msg.images)
                        for img_data in images:
                            content_parts.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": img_data
                                }
                            })
                    except:
                        pass
                    openai_messages.append({
                        "role": "user",
                        "content": content_parts
                    })
                else:
                    openai_messages.append({
                        "role": msg.role,
                        "content": get_message_content(msg, selected_versions)
                    })

        user_message_for_model = user_message
        assistant_extra_payload: Dict = {}
        conversation_obj = await conversation_crud.get(chat_db, conversation_id)
        conversation_extra = parse_conversation_extra(conversation_obj.extra if conversation_obj else None)
        extra_changed = False

        detected_targets = extract_arxiv_targets(user_message)
        if detected_targets:
            discovered_entries = [
                {
                    "paper_id": t.paper_id,
                    "canonical_id": t.canonical_id,
                    "safe_id": t.safe_id,
                    "filename": f"{t.safe_id}.pdf",
                    "pdf_url": f"/papers/{t.safe_id}/{t.safe_id}.pdf",
                }
                for t in detected_targets
            ]
            conversation_extra = upsert_registry_entries(conversation_extra, discovered_entries)
            conversation_extra = activate_papers_in_conversation(
                conversation_extra,
                [t.canonical_id for t in detected_targets],
                max_active=settings.ARXIV_MAX_ACTIVE_PAPERS,
            )
            extra_changed = True

        active_entries = get_active_registry_entries(conversation_extra)
        active_targets = []
        for item in active_entries:
            target = build_target_from_ids(
                paper_id=str(item.get("paper_id") or ""),
                canonical_id=str(item.get("canonical_id") or ""),
            )
            if target:
                active_targets.append(target)

        arxiv_context = None
        if active_targets:
            history_user_queries = [
                str(msg.content or "").strip()
                for msg in messages_history
                if msg.role == "user" and str(msg.content or "").strip()
            ]
            rewrite_api_config = {
                "api_key": str(getattr(api_config, "api_key", "") or ""),
                "base_url": str(getattr(api_config, "base_url", "") or ""),
            }
            progress_queue: asyncio.Queue[Dict] = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def progress_reporter(payload: Dict) -> None:
                loop.call_soon_threadsafe(progress_queue.put_nowait, payload)

            worker_task = asyncio.create_task(
                asyncio.to_thread(
                    build_arxiv_context_for_targets,
                    user_message,
                    active_targets,
                    settings,
                    progress_reporter,
                    history_user_queries,
                    rewrite_api_config,
                )
            )
            try:
                while not worker_task.done():
                    try:
                        progress_payload = await asyncio.wait_for(progress_queue.get(), timeout=0.12)
                        status_data = json.dumps(progress_payload, ensure_ascii=False)
                        yield f"event: status\ndata: {status_data}\n\n"
                    except asyncio.TimeoutError:
                        continue

                while not progress_queue.empty():
                    progress_payload = progress_queue.get_nowait()
                    status_data = json.dumps(progress_payload, ensure_ascii=False)
                    yield f"event: status\ndata: {status_data}\n\n"

                arxiv_context = await worker_task
            except ArxivPipelineError as exc:
                error_data = json.dumps({"error": str(exc)})
                yield f"event: error\ndata: {error_data}\n\n"
                return

        if arxiv_context:
            openai_messages.append(
                {
                    "role": "system",
                    "content": arxiv_context.context_prompt,
                }
            )
            # 检索 query 会去掉 arXiv 链接；但送给模型的用户消息保持原始输入。
            user_message_for_model = user_message
            assistant_extra_payload["retrieval"] = arxiv_context.retrieval_meta
            conversation_extra = upsert_registry_entries(conversation_extra, arxiv_context.papers)
            extra_changed = True
            logger.info(
                "chat-arxiv-injected papers=%s query=%s",
                ",".join(p.get("paper_id", "") for p in arxiv_context.papers),
                (user_message_for_model or "")[:180],
            )
        elif "arxiv.org" in (user_message or "").lower() and not detected_targets:
            logger.info("chat-arxiv-skipped reason=invalid-or-unsupported-id")

        if extra_changed and conversation_obj:
            await conversation_crud.set_extra(
                chat_db,
                conversation_id,
                serialize_conversation_extra(conversation_extra),
            )

        # 添加当前用户消息（支持图片）
        # 重试时不重复添加当前用户消息，避免重复输入
        if not retry_message_id:
            if user_images and len(user_images) > 0:
                # 带图片的消息，使用 vision API 格式
                content_parts = [{"type": "text", "text": user_message_for_model}] if user_message_for_model else []
                for img_data in user_images:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": img_data
                        }
                    })
                openai_messages.append({
                    "role": "user",
                    "content": content_parts
                })
            else:
                # 纯文本消息
                openai_messages.append({
                    "role": "user",
                    "content": user_message_for_model
                })
        
        # 5. 如果不是重试，使用 chat_db 保存用户消息到数据库
        if not retry_message_id:
            images_json = json.dumps(user_images) if user_images else None
            await message_crud.create(chat_db, conversation_id, "user", user_message, images_json)
        
        # 6. 生成消息ID
        import uuid
        message_id = retry_message_id or str(uuid.uuid4())
        
        # 发送开始事件
        start_data = json.dumps({"message_id": message_id})
        yield f"event: start\ndata: {start_data}\n\n"
        
        # 7. 调用流式API
        if not api_config or not getattr(api_config, "model", None):
            error_data = json.dumps({"error": "未提供模型，请在前端选择模型"})
            yield f"event: error\ndata: {error_data}\n\n"
            return
        use_proxy = api_config.model in settings.proxy_models_list
        if use_proxy and not settings.proxy_enabled:
            error_data = json.dumps({"error": "未配置 Chat2API 代理"})
            yield f"event: error\ndata: {error_data}\n\n"
            return
        active_streams[conversation_id] = True

        stream_iter = (
            stream_chat2api_completion(
                settings.PROXY_BASE_URL,
                settings.ACCESS_TOKEN,
                api_config.model,
                openai_messages,
                temperature=api_config.temperature,
                max_tokens=api_config.max_tokens,
                top_p=api_config.top_p,
                frequency_penalty=api_config.frequency_penalty,
                presence_penalty=api_config.presence_penalty,
            )
            if use_proxy
            else stream_chat_completion(api_config, openai_messages)
        )

        async def persist_assistant() -> Optional[Dict]:
            nonlocal assistant_saved, assistant_msg
            if assistant_saved or not full_response:
                return None
            cost_meta: Optional[Dict] = None
            if usage_data and not use_proxy:
                prompt_tokens = int(usage_data.get("prompt_tokens") or 0)
                completion_tokens = int(usage_data.get("completion_tokens") or 0)
                if prompt_tokens or completion_tokens:
                    cost_meta = compute_text_cost(
                        api_config.model,
                        prompt_tokens,
                        completion_tokens,
                    )
            cost_meta_json = json.dumps(cost_meta, ensure_ascii=False) if cost_meta else None
            thinking_text = thinking_response if thinking_response else None
            assistant_extra_json = (
                json.dumps(assistant_extra_payload, ensure_ascii=False)
                if assistant_extra_payload
                else None
            )

            if retry_message_id:
                update_msg = await message_crud.get(chat_db, retry_message_id)
                if update_msg:
                    retry_versions = []
                    if update_msg.retry_versions:
                        try:
                            retry_versions = json.loads(update_msg.retry_versions)
                        except:
                            retry_versions = []
                    retry_versions.append(update_msg.content)
                    update_msg.content = full_response
                    update_msg.cost_meta = cost_meta_json
                    update_msg.thinking = thinking_text
                    update_msg.retry_versions = json.dumps(retry_versions)
                    update_msg.extra = assistant_extra_json
                    await message_crud.update(chat_db, retry_message_id, update_msg)
                    assistant_msg = update_msg
            else:
                assistant_msg = await message_crud.create(
                    chat_db,
                    conversation_id,
                    "assistant",
                    full_response,
                    cost_meta=cost_meta_json,
                    thinking=thinking_text,
                    extra=assistant_extra_json,
                )

            assistant_saved = True
            return cost_meta

        async for event in stream_iter:
            # 检查是否被停止
            if not active_streams.get(conversation_id, False):
                stopped_by_user = True
                break
            
            # 检查是否是错误
            if event.get("type") == "error":
                yield f"event: error\ndata: {json.dumps({'error': event.get('error')})}\n\n"
                break
            
            if event.get("type") == "usage":
                usage_data = event.get("usage")
                continue
            
            if event.get("type") == "thinking":
                thinking_chunk = event.get("content", "")
                thinking_response += thinking_chunk
                thinking_data = json.dumps({"content": thinking_chunk})
                yield f"event: thinking\ndata: {thinking_data}\n\n"
                continue
            
            if event.get("type") != "token":
                continue
            chunk = event.get("content", "")
            full_response += chunk
            chunk_data = json.dumps({"content": chunk})
            yield f"event: token\ndata: {chunk_data}\n\n"

        # 8. 使用 chat_db 保存AI响应到数据库
        if full_response and (active_streams.get(conversation_id, False) or stopped_by_user):
            cost_meta = await persist_assistant()
            message_obj = {
                "message_id": message_id,
                "finish_reason": "stopped" if stopped_by_user else "stop"
            }
            if assistant_msg:
                extra_obj = None
                if assistant_msg.extra:
                    try:
                        extra_obj = json.loads(assistant_msg.extra)
                    except Exception:
                        extra_obj = None
                message_obj["message"] = {
                    "id": assistant_msg.id,
                    "conversation_id": assistant_msg.conversation_id,
                    "role": assistant_msg.role,
                    "content": assistant_msg.content,
                    "retry_versions": assistant_msg.retry_versions,
                    "cost_meta": cost_meta,
                    "thinking": assistant_msg.thinking,
                    "extra": extra_obj,
                    "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
                }
            done_data = json.dumps(message_obj)
            if stopped_by_user:
                yield f"event: stopped\ndata: {done_data}\n\n"
            else:
                yield f"event: done\ndata: {done_data}\n\n"
        elif stopped_by_user:
            stopped_data = json.dumps({
                "message_id": message_id,
                "finish_reason": "stopped"
            })
            yield f"event: stopped\ndata: {stopped_data}\n\n"
        
        # 清理
        if conversation_id in active_streams:
            del active_streams[conversation_id]
    
    except asyncio.CancelledError:
        cancelled = True
        # 客户端断开/取消时，避免传播取消导致连接关闭异常
        # 留给 finally 做持久化和清理
        return
    except Exception as e:
        error_data = json.dumps({"error": f"服务器错误: {str(e)}"})
        yield f"event: error\ndata: {error_data}\n\n"
        
        # 清理
        if conversation_id in active_streams:
            del active_streams[conversation_id]
    finally:
        if (stopped_by_user or cancelled) and full_response and not assistant_saved:
            try:
                await persist_assistant()
            except Exception:
                pass
        if conversation_id in active_streams:
            del active_streams[conversation_id]


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    chat_db: AsyncSession = Depends(get_chat_session),
    tools_db: AsyncSession = Depends(get_session)
):
    """流式聊天接口（SSE）"""
    
    # 使用 chat_db 验证会话是否存在
    conversation = await conversation_crud.get(chat_db, request.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 验证工具是否存在（如果提供了tool_id），使用 tools_db
    if request.tool_id:
        tool = await tool_crud.get(tools_db, request.tool_id)
        if not tool:
            raise HTTPException(status_code=404, detail="工具不存在")
    
    return StreamingResponse(
        generate_chat_stream(
            request.conversation_id,
            request.tool_id,
            request.message,
            request.images or [],
            request.api_config,
            chat_db,
            tools_db,
            request.retry_message_id,
            request.selected_versions,
            request.context_rounds,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用nginx缓冲
        }
    )


@router.post("/chat/stop")
async def stop_chat(request: StopChatRequest):
    """停止生成"""
    if request.conversation_id in active_streams:
        active_streams[request.conversation_id] = False
        return {"success": True, "message": "已发送停止信号"}
    
    return {"success": False, "message": "没有正在进行的生成"}
