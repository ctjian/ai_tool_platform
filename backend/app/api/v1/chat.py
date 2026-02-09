"""聊天API（流式输出）"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator, Optional, Dict
import os
import json

from app.database import get_session, get_chat_session
from app.crud.conversation import conversation_crud, message_crud
from app.crud.tool import tool_crud
from app.schemas.chat import ChatRequest, StopChatRequest
from app.utils.openai_helper import stream_chat_completion
from app.utils.pricing import compute_text_cost
from app.utils.system_prompt import get_default_system_prompt, pick_system_prompt

router = APIRouter()

# 全局字典存储正在进行的流式请求（用于停止功能）
active_streams = {}
DEBUG_THINKING = os.getenv("DEBUG_THINKING") == "1"



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
        # 通用对话：从历史 system 消息取系统提示词
        if not tool_id:
            system_prompt = pick_system_prompt(messages_history)
        if not system_prompt:
            system_prompt = get_default_system_prompt()

        # 过滤 system 消息（避免重复传入）
        messages_history = [m for m in messages_history if m.role != "system"]

        if context_rounds:
            # 保留最近N轮（以用户消息为轮次起点）
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
        
        # 添加当前用户消息（支持图片）
        # 重试时不重复添加当前用户消息，避免重复输入
        if not retry_message_id:
            if user_images and len(user_images) > 0:
                # 带图片的消息，使用 vision API 格式
                content_parts = [{"type": "text", "text": user_message}] if user_message else []
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
                    "content": user_message
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
        
        # 7. 调用OpenAI流式API
        if not api_config or not getattr(api_config, "model", None):
            error_data = json.dumps({"error": "未提供模型，请在前端选择模型"})
            yield f"event: error\ndata: {error_data}\n\n"
            return
        full_response = ""
        thinking_response = ""
        usage_data: Optional[Dict] = None
        active_streams[conversation_id] = True
        
        async for event in stream_chat_completion(api_config, openai_messages):
            # 检查是否被停止
            if not active_streams.get(conversation_id, False):
                yield f"event: stopped\ndata: {json.dumps({'message': '生成已停止'})}\n\n"
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
                if DEBUG_THINKING and thinking_chunk:
                    print(f"[thinking] chunk_len={len(thinking_chunk)} total_len={len(thinking_response)}")
                continue
            
            if event.get("type") != "token":
                continue
            chunk = event.get("content", "")
            full_response += chunk
            chunk_data = json.dumps({"content": chunk})
            yield f"event: token\ndata: {chunk_data}\n\n"
        
        # 8. 使用 chat_db 保存AI响应到数据库
        if full_response and active_streams.get(conversation_id, False):
            cost_meta: Optional[Dict] = None
            if usage_data:
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
            if DEBUG_THINKING:
                print(
                    f"[thinking] done model={api_config.model} "
                    f"thinking_len={len(thinking_response)} "
                    f"has_usage={bool(usage_data)}"
                )

            assistant_msg = None
            if retry_message_id:
                # 重试情况：更新现有消息，将当前content移动到retry_versions
                update_msg = await message_crud.get(chat_db, retry_message_id)
                if update_msg:
                    # 获取现有的重试版本
                    retry_versions = []
                    if update_msg.retry_versions:
                        try:
                            retry_versions = json.loads(update_msg.retry_versions)
                        except:
                            retry_versions = []
                    
                    # 将当前内容添加到重试版本历史
                    retry_versions.append(update_msg.content)
                    
                    # 更新消息：新内容作为当前content，旧内容存入retry_versions
                    update_msg.content = full_response
                    update_msg.cost_meta = cost_meta_json
                    update_msg.thinking = thinking_text
                    update_msg.retry_versions = json.dumps(retry_versions)
                    await message_crud.update(chat_db, retry_message_id, update_msg)
                    assistant_msg = update_msg
            else:
                # 正常情况：创建新消息
                assistant_msg = await message_crud.create(
                    chat_db,
                    conversation_id,
                    "assistant",
                    full_response,
                    cost_meta=cost_meta_json,
                    thinking=thinking_text,
                )
            
            # 发送完成事件 - 包含完整的消息对象
            message_obj = {
                "message_id": message_id,
                "finish_reason": "stop"
            }
            
            if assistant_msg:
                message_obj["message"] = {
                    "id": assistant_msg.id,
                    "conversation_id": assistant_msg.conversation_id,
                    "role": assistant_msg.role,
                    "content": assistant_msg.content,
                    "retry_versions": assistant_msg.retry_versions,
                    "cost_meta": cost_meta,
                    "thinking": assistant_msg.thinking,
                    "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
                }
            
            done_data = json.dumps(message_obj)
            yield f"event: done\ndata: {done_data}\n\n"
        
        # 清理
        if conversation_id in active_streams:
            del active_streams[conversation_id]
    
    except Exception as e:
        error_data = json.dumps({"error": f"服务器错误: {str(e)}"})
        yield f"event: error\ndata: {error_data}\n\n"
        
        # 清理
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
