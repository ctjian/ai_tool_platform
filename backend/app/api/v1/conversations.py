"""会话管理API"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import os
from typing import List, Optional, Dict, Any
import json

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
)
from app.utils.openai_helper import generate_title_for_conversation
from app.models.message import Message

router = APIRouter()
DEBUG_THINKING = os.getenv("DEBUG_THINKING") == "1"


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
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    system_msg = result.scalar_one_or_none()
    if system_msg:
        system_msg.content = content
        await db.commit()
        await db.refresh(system_msg)
        return system_msg

    return await message_crud.create(
        db,
        conversation_id=conversation_id,
        role="system",
        content=content,
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

    if DEBUG_THINKING:
        thinking_msgs = [m for m in conversation.messages if getattr(m, "thinking", None)]
        sample_len = len(thinking_msgs[0].thinking) if thinking_msgs else 0
        print(
            f"[thinking] conv={conversation_id} total={len(conversation.messages)} "
            f"thinking_msgs={len(thinking_msgs)} sample_len={sample_len}"
        )
    
    # 构建响应
    messages = []
    for msg in conversation.messages:
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
                created_at=msg.created_at
            )
        )
    
    message_count = len(messages)
    
    return ConversationDetailResponse(
        id=conversation.id,
        tool_id=conversation.tool_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=message_count,
        messages=messages,
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
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=message_count,
    )


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
        print(f"标题生成错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生成标题失败: {str(e)}")
