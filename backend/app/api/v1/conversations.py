"""会话管理API

Review note:
- 会话/消息的扩展状态通过 `extra` JSON 管理。
- 增加 paper 资源 API：查询、激活、取消激活。
"""
from fastapi import APIRouter, Depends, HTTPException, Body, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import json
import logging
import secrets
import shutil
import re
from pathlib import Path

from app.database import get_session, get_chat_session
from app.crud.conversation import conversation_crud, message_crud
from app.crud.tool import tool_crud
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ExportConversationResponse,
    MessageResponse,
    MessageRoundPromptResponse,
)
from app.utils.openai_helper import generate_title_for_conversation
from app.models.message import Message
from app.config import settings
from app.services.cache.paper_store import build_paper_paths, ensure_paper_dir, load_meta, save_meta
from app.services.session.paper_state import (
    list_papers_from_extra,
    activate_papers_in_conversation,
    deactivate_paper_in_conversation,
    remove_paper_from_conversation,
    upsert_registry_entries,
    parse_conversation_extra,
    serialize_conversation_extra,
    normalize_state,
)
from app.services.sources.arxiv.id_parser import safe_id_from_canonical

router = APIRouter()
logger = logging.getLogger("uvicorn.error")


def _parse_message_extra(raw_extra: Any) -> Optional[Dict[str, Any]]:
    if raw_extra is None:
        return None
    if isinstance(raw_extra, dict):
        return dict(raw_extra)
    if isinstance(raw_extra, str):
        try:
            parsed = json.loads(raw_extra)
            return dict(parsed) if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    return None


def _extract_round_prompt(extra: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(extra, dict):
        return None
    payload = extra.get("round_prompt")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError, ValueError):
            payload = None
    return payload if isinstance(payload, dict) else None


def _has_round_prompt(extra: Optional[Dict[str, Any]]) -> bool:
    payload = _extract_round_prompt(extra)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    return isinstance(messages, list) and len(messages) > 0


def _strip_round_prompt(extra: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(extra, dict):
        return extra
    if "round_prompt" not in extra:
        return extra
    sanitized = {k: v for k, v in extra.items() if k != "round_prompt"}
    return sanitized or None


def _sanitize_display_pdf_name(raw_name: str) -> str:
    name = Path(str(raw_name or "")).name.strip()
    if not name:
        return "uploaded.pdf"
    # 仅用于显示，路径保存使用 safe_id，不使用原始文件名。
    name = re.sub(r"[\x00-\x1f\x7f]+", "", name)
    name = name.replace("/", "_").replace("\\", "_")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    if len(name) > 128:
        base = name[:-4]
        name = f"{base[:120]}.pdf"
    return name or "uploaded.pdf"


def _generate_upload_canonical_id(existing_ids: set[str]) -> str:
    for _ in range(64):
        candidate = f"upload/{secrets.randbelow(10_000_000):07d}"
        if candidate not in existing_ids:
            return candidate
    raise RuntimeError("无法生成唯一上传资源ID，请重试")


async def upsert_system_prompt(
    db: AsyncSession,
    conversation_id: str,
    content: Optional[str],
):
    trimmed = (content or "").strip()
    if not trimmed:
        await db.execute(
            delete(Message).where(
                Message.conversation_id == conversation_id,
                Message.role == "system",
            )
        )
        await db.commit()
        return None

    result = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.role == "system",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
    )
    system_messages = list(result.scalars().all())
    if system_messages:
        system_msg = system_messages[0]
        system_msg.content = trimmed
        duplicate_ids = [msg.id for msg in system_messages[1:]]
        if duplicate_ids:
            await db.execute(delete(Message).where(Message.id.in_(duplicate_ids)))
        await db.commit()
        await db.refresh(system_msg)
        return system_msg

    return await message_crud.create(
        db,
        conversation_id=conversation_id,
        role="system",
        content=trimmed,
        images=None,
        cost_meta=None,
        thinking=None,
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(
    tool_id: str = None,
    db: AsyncSession = Depends(get_chat_session)
):
    """获取会话列表，如果指定tool_id则获取该工具的会话，否则获取全部会话"""
    if tool_id:
        conversations = await conversation_crud.get_by_tool(db, tool_id)
    else:
        # 获取所有会话
        conversations = await conversation_crud.get_all(db)
    
    # 获取每个会话的消息数量
    result = []
    for conv in conversations:
        message_count = await conversation_crud.get_message_count(db, conv.id)
        conv_dict = {
            "id": conv.id,
            "tool_id": conv.tool_id,
            "title": conv.title,
            "extra": conv.extra,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "message_count": message_count,
        }
        result.append(ConversationResponse(**conv_dict))
    
    return {"conversations": result}


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_chat_session)
):
    """获取会话详情（包含消息）"""
    conversation = await conversation_crud.get(db, conversation_id, with_messages=True)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 构建响应
    messages = []
    ordered_messages = sorted(
        conversation.messages,
        key=lambda msg: (msg.created_at, msg.id),
    )
    for msg in ordered_messages:
        extra = _parse_message_extra(msg.extra)
        has_round_prompt = _has_round_prompt(extra)
        # 解析图片JSON
        images = None
        if msg.images:
            try:
                images = json.loads(msg.images)
            except (json.JSONDecodeError, TypeError):
                images = None
        
        retry_versions = None
        if msg.retry_versions:
            try:
                retry_versions = json.loads(msg.retry_versions)
            except (json.JSONDecodeError, TypeError):
                retry_versions = None

        messages.append(
            MessageResponse(
                id=msg.id,
                conversation_id=msg.conversation_id,
                role=msg.role,
                content=msg.content,
                images=images,
                retry_versions=retry_versions,
                cost_meta=msg.cost_meta,
                thinking=msg.thinking,
                extra=_strip_round_prompt(extra),
                has_round_prompt=has_round_prompt,
                created_at=msg.created_at
            )
        )
    
    message_count = len(messages)
    
    return ConversationDetailResponse(
        id=conversation.id,
        tool_id=conversation.tool_id,
        title=conversation.title,
        extra=conversation.extra,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=message_count,
        messages=messages,
    )


@router.get(
    "/conversations/{conversation_id}/messages/{message_id}/round-prompt",
    response_model=MessageRoundPromptResponse,
)
async def get_message_round_prompt(
    conversation_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_chat_session),
):
    """按需获取消息的提示词快照。"""
    message = await message_crud.get(db, message_id)
    if not message or message.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="消息不存在")

    extra = _parse_message_extra(message.extra)
    payload = _extract_round_prompt(extra)
    has_round_prompt = _has_round_prompt(extra)
    return MessageRoundPromptResponse(
        message_id=message_id,
        has_round_prompt=has_round_prompt,
        round_prompt=payload if has_round_prompt else None,
    )


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    conversation_in: ConversationCreate,
    chat_db: AsyncSession = Depends(get_chat_session),
    tools_db: AsyncSession = Depends(get_session)
):
    """创建新会话"""
    # 如果指定了tool_id，使用 tools_db 检查工具是否存在
    if conversation_in.tool_id:
        tool = await tool_crud.get(tools_db, conversation_in.tool_id)
        if not tool:
            raise HTTPException(status_code=400, detail="工具不存在")
    
    # 使用 chat_db 创建会话
    conversation = await conversation_crud.create(chat_db, conversation_in)
    
    return ConversationResponse(
        id=conversation.id,
        tool_id=conversation.tool_id,
        title=conversation.title,
        extra=conversation.extra,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=0,
    )


@router.put("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: str,
    conversation_in: ConversationUpdate,
    db: AsyncSession = Depends(get_chat_session)
):
    """更新会话（主要是修改标题）"""
    # 确认会话存在
    existing = await conversation_crud.get(db, conversation_id)
    if not existing:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 先处理 system prompt 更新（写入 system 消息）
    if conversation_in.system_prompt is not None:
        await upsert_system_prompt(db, conversation_id, conversation_in.system_prompt)
    
    # 再处理标题更新
    conversation = None
    if conversation_in.title is not None:
        conversation = await conversation_crud.update(db, conversation_id, conversation_in)
    else:
        conversation = existing
    
    message_count = await conversation_crud.get_message_count(db, conversation_id)
    
    return ConversationResponse(
        id=conversation.id,
        tool_id=conversation.tool_id,
        title=conversation.title,
        extra=conversation.extra,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=message_count,
    )


@router.get("/conversations/{conversation_id}/papers")
async def get_conversation_papers(
    conversation_id: str,
    db: AsyncSession = Depends(get_chat_session),
):
    """获取会话论文资源（registry + active_ids）。"""
    conversation = await conversation_crud.get(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    extra_dict = parse_conversation_extra(conversation.extra)
    return list_papers_from_extra(extra_dict)


@router.get("/conversations/{conversation_id}/papers/{canonical_id}/sections")
async def get_conversation_paper_sections(
    conversation_id: str,
    canonical_id: str,
    db: AsyncSession = Depends(get_chat_session),
):
    """获取论文章节列表（用于 section 选择）。"""
    conversation = await conversation_crud.get(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")

    canonical_id = str(canonical_id or "").strip()
    if not canonical_id:
        raise HTTPException(status_code=400, detail="缺少 canonical_id")

    extra_dict = parse_conversation_extra(conversation.extra)
    state = normalize_state(extra_dict)
    entry = state["papers"]["registry"].get(canonical_id)
    if not entry:
        raise HTTPException(status_code=404, detail="论文不存在")

    safe_id = str(entry.get("safe_id") or safe_id_from_canonical(canonical_id)).strip()
    paths = build_paper_paths(settings.PAPER_DATA_DIR, safe_id)
    meta = load_meta(paths) or {}
    raw_sections = meta.get("sections") if isinstance(meta, dict) else None
    sections = []
    if isinstance(raw_sections, list):
        for sec in raw_sections:
            if not isinstance(sec, dict):
                continue
            section_id = str(sec.get("section_id") or "").strip()
            title = str(sec.get("title") or "").strip()
            if not section_id or not title:
                continue
            sections.append(
                {
                    "section_id": section_id,
                    "title": title,
                    "level": sec.get("level"),
                    "order": sec.get("order"),
                }
            )
        sections.sort(key=lambda x: int(x.get("order") or 0))

    return {
        "canonical_id": canonical_id,
        "ready": bool(raw_sections),
        "sections": sections,
    }


@router.post("/conversations/{conversation_id}/papers/activate")
async def activate_conversation_papers(
    conversation_id: str,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_chat_session),
):
    """激活一篇或多篇论文（不删除 registry）。"""
    conversation = await conversation_crud.get(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")

    canonical_ids = payload.get("canonical_ids")
    canonical_id = payload.get("canonical_id")
    if not isinstance(canonical_ids, list):
        canonical_ids = [canonical_id] if canonical_id else []
    canonical_ids = [str(x).strip() for x in canonical_ids if str(x).strip()]
    if not canonical_ids:
        raise HTTPException(status_code=400, detail="缺少 canonical_id(s)")

    extra_dict = parse_conversation_extra(conversation.extra)
    updated = activate_papers_in_conversation(
        extra=extra_dict,
        canonical_ids=canonical_ids,
        max_active=settings.ARXIV_MAX_ACTIVE_PAPERS,
    )
    await conversation_crud.set_extra(db, conversation_id, serialize_conversation_extra(updated))
    return list_papers_from_extra(updated)


@router.post("/conversations/{conversation_id}/papers/deactivate")
async def deactivate_conversation_paper(
    conversation_id: str,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_chat_session),
):
    """取消激活论文（保留 registry，可重新激活）。"""
    conversation = await conversation_crud.get(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    canonical_id = str(payload.get("canonical_id") or "").strip()
    if not canonical_id:
        raise HTTPException(status_code=400, detail="缺少 canonical_id")

    extra_dict = parse_conversation_extra(conversation.extra)
    updated = deactivate_paper_in_conversation(extra_dict, canonical_id)
    await conversation_crud.set_extra(db, conversation_id, serialize_conversation_extra(updated))
    return list_papers_from_extra(updated)


@router.post("/conversations/{conversation_id}/papers/section-filter")
async def update_conversation_paper_section_filter(
    conversation_id: str,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_chat_session),
):
    """更新论文章节筛选（存入 conversation extra）。"""
    conversation = await conversation_crud.get(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")

    canonical_id = str(payload.get("canonical_id") or "").strip()
    if not canonical_id:
        raise HTTPException(status_code=400, detail="缺少 canonical_id")

    section_ids_raw = payload.get("section_ids")
    if section_ids_raw is None:
        section_ids_raw = []
    if not isinstance(section_ids_raw, list):
        raise HTTPException(status_code=400, detail="section_ids 必须为数组")
    section_ids = [str(x).strip() for x in section_ids_raw if str(x).strip()]

    extra_dict = parse_conversation_extra(conversation.extra)
    state = normalize_state(extra_dict)
    entry = state["papers"]["registry"].get(canonical_id)
    if not entry:
        raise HTTPException(status_code=404, detail="论文不存在")

    if section_ids:
        entry["section_filter"] = {
            "mode": "selected",
            "section_ids": section_ids,
        }
    else:
        entry.pop("section_filter", None)

    state["papers"]["registry"][canonical_id] = entry
    await conversation_crud.set_extra(db, conversation_id, serialize_conversation_extra(state))
    return list_papers_from_extra(state)


@router.post("/conversations/{conversation_id}/papers/upload-pdf")
async def upload_conversation_pdfs(
    conversation_id: str,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_chat_session),
):
    """上传一批 PDF 到会话资源并默认激活。"""
    conversation = await conversation_crud.get(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")

    if not files:
        raise HTTPException(status_code=400, detail="缺少上传文件")
    max_files = max(1, int(getattr(settings, "CHAT_MAX_PDF_FILES", 5) or 5))
    if len(files) > max_files:
        raise HTTPException(status_code=400, detail=f"单次最多上传 {max_files} 个 PDF")

    max_size_mb = max(1, int(getattr(settings, "CHAT_MAX_PDF_SIZE_MB", 20) or 20))
    max_size_bytes = max_size_mb * 1024 * 1024

    extra_dict = parse_conversation_extra(conversation.extra)
    state = normalize_state(extra_dict)
    existing_ids = set(state["papers"]["registry"].keys())
    new_entries: list[Dict[str, Any]] = []
    new_ids: list[str] = []

    for upload in files:
        display_name = _sanitize_display_pdf_name(upload.filename or "")
        if not display_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"文件必须为 PDF: {display_name}")

        data = await upload.read()
        size = len(data)
        if size <= 0:
            raise HTTPException(status_code=400, detail=f"空文件无法上传: {display_name}")
        if size > max_size_bytes:
            raise HTTPException(status_code=400, detail=f"{display_name} 超过 {max_size_mb}MB 限制")

        canonical_id = _generate_upload_canonical_id(existing_ids)
        existing_ids.add(canonical_id)
        safe_id = safe_id_from_canonical(canonical_id)
        paths = build_paper_paths(settings.PAPER_DATA_DIR, safe_id)
        ensure_paper_dir(paths)
        paths.pdf_path.write_bytes(data)
        meta = load_meta(paths) or {}
        source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
        source["type"] = "upload_pdf"
        meta.update(
            {
                "paper_id": canonical_id,
                "canonical_id": canonical_id,
                "safe_id": safe_id,
                "origin_name": display_name,
                "source": source,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        save_meta(paths, meta)

        new_ids.append(canonical_id)
        new_entries.append(
            {
                "canonical_id": canonical_id,
                "paper_id": canonical_id,
                "safe_id": safe_id,
                "filename": display_name,
                "origin_name": display_name,
                "title": display_name,
                "source_type": "upload_pdf",
                "pdf_url": f"/papers/{safe_id}/{safe_id}.pdf",
            }
        )

    updated = upsert_registry_entries(extra_dict, new_entries)
    updated = activate_papers_in_conversation(
        updated,
        canonical_ids=new_ids,
        max_active=settings.ARXIV_MAX_ACTIVE_PAPERS,
    )
    await conversation_crud.set_extra(db, conversation_id, serialize_conversation_extra(updated))
    return list_papers_from_extra(updated)


@router.post("/conversations/{conversation_id}/papers/delete")
async def delete_conversation_paper(
    conversation_id: str,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_chat_session),
):
    """彻底删除会话资源（含本地文件目录）。"""
    conversation = await conversation_crud.get(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")

    canonical_id = str(payload.get("canonical_id") or "").strip()
    if not canonical_id:
        raise HTTPException(status_code=400, detail="缺少 canonical_id")

    extra_dict = parse_conversation_extra(conversation.extra)
    state = normalize_state(extra_dict)
    item = state["papers"]["registry"].get(canonical_id)
    if not item:
        raise HTTPException(status_code=404, detail="资源不存在")

    updated = remove_paper_from_conversation(extra_dict, canonical_id)
    await conversation_crud.set_extra(db, conversation_id, serialize_conversation_extra(updated))

    safe_id = str(item.get("safe_id") or "").strip()
    if safe_id:
        root = Path(settings.PAPER_DATA_DIR).resolve()
        target_dir = (root / safe_id).resolve()
        try:
            target_dir.relative_to(root)
            if target_dir.exists():
                shutil.rmtree(target_dir)
        except Exception:
            logger.warning("skip-delete-paper-dir canonical_id=%s safe_id=%s", canonical_id, safe_id)

    return list_papers_from_extra(updated)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_chat_session)
):
    """删除会话"""
    success = await conversation_crud.delete(db, conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True, "message": "会话已删除"}


@router.delete("/conversations/{conversation_id}/messages")
async def clear_conversation_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_chat_session)
):
    """清空会话的所有消息"""
    # 检查会话是否存在
    conversation = await conversation_crud.get(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    await message_crud.delete_by_conversation(db, conversation_id)
    return {"success": True, "message": "消息已清空", "conversation_id": conversation_id}


@router.get("/conversations/{conversation_id}/export", response_model=ExportConversationResponse)
async def export_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_chat_session)
):
    """导出会话为Markdown格式"""
    conversation = await conversation_crud.get(db, conversation_id, with_messages=True)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 生成Markdown内容
    markdown_lines = [
        f"# {conversation.title}",
        "",
        f"**工具ID**: {conversation.tool_id}",
        f"**创建时间**: {conversation.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**更新时间**: {conversation.updated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
    ]
    
    for msg in conversation.messages:
        role_name = {
            "user": "👤 User",
            "assistant": "🤖 Assistant",
            "system": "⚙️ System"
        }.get(msg.role, msg.role)
        
        markdown_lines.extend([
            f"## {role_name}",
            "",
            msg.content,
            "",
            f"*{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
            "---",
            "",
        ])
    
    markdown_content = "\n".join(markdown_lines)
    
    return {"markdown": markdown_content}


@router.post("/conversations/{conversation_id}/generate-title")
async def generate_conversation_title(
    conversation_id: str,
    db: AsyncSession = Depends(get_chat_session),
    body: Optional[Dict[str, Any]] = Body(None),
):
    """自动生成对话标题"""
    # 获取会话
    conversation = await conversation_crud.get(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 获取会话的消息
    messages = await message_crud.get_by_conversation(db, conversation_id)
    if not messages:
        raise HTTPException(status_code=400, detail="会话中没有消息")
    
    # 从请求体中提取 api_config
    api_config = None
    if body and isinstance(body, dict):
        api_config = body.get('api_config')
    
    # 生成标题
    try:
        title = await generate_title_for_conversation(messages, api_config)
        
        # 更新会话标题
        updated_conv = await conversation_crud.update(
            db,
            conversation_id,
            ConversationUpdate(title=title)
        )
        
        return {
            "success": True,
            "title": title,
            "conversation_id": conversation_id
        }
    except Exception as e:
        logger.exception("标题生成错误 conversation_id=%s", conversation_id)
        raise HTTPException(status_code=500, detail=f"生成标题失败: {str(e)}")
