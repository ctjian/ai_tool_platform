"""会话和消息的CRUD操作

Review note:
- Conversation/Message 的 `extra` 字段用于保存可扩展 JSON 状态。
- 本文件提供对 `extra` 的基础读写接口，供上层会话状态逻辑复用。
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import datetime
import uuid

from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.conversation import ConversationCreate, ConversationUpdate


class CRUDConversation:
    """会话CRUD操作"""
    
    async def get(
        self, 
        db: AsyncSession, 
        conversation_id: str,
        with_messages: bool = False
    ) -> Optional[Conversation]:
        """获取单个会话"""
        query = select(Conversation).where(Conversation.id == conversation_id)
        if with_messages:
            query = query.options(selectinload(Conversation.messages))
        
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_tool(
        self, 
        db: AsyncSession, 
        tool_id: str
    ) -> List[Conversation]:
        """获取工具的所有会话"""
        result = await db.execute(
            select(Conversation)
            .where(Conversation.tool_id == tool_id)
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())
    
    async def get_all(
        self, 
        db: AsyncSession
    ) -> List[Conversation]:
        """获取所有会话"""
        result = await db.execute(
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())
    
    async def create(
        self, 
        db: AsyncSession, 
        obj_in: ConversationCreate
    ) -> Conversation:
        """创建会话"""
        conversation_id = str(uuid.uuid4())
        title = f"新对话 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        db_obj = Conversation(
            id=conversation_id,
            tool_id=obj_in.tool_id,
            title=title,
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    
    async def update(
        self, 
        db: AsyncSession, 
        conversation_id: str, 
        obj_in: ConversationUpdate
    ) -> Optional[Conversation]:
        """更新会话"""
        db_obj = await self.get(db, conversation_id)
        if not db_obj:
            return None
        
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def set_extra(
        self,
        db: AsyncSession,
        conversation_id: str,
        extra: Optional[str],
    ) -> Optional[Conversation]:
        """更新会话 extra JSON 字符串。"""
        db_obj = await self.get(db, conversation_id)
        if not db_obj:
            return None
        db_obj.extra = extra
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    
    async def delete(self, db: AsyncSession, conversation_id: str) -> bool:
        """删除会话"""
        result = await db.execute(
            delete(Conversation).where(Conversation.id == conversation_id)
        )
        await db.commit()
        return result.rowcount > 0
    
    async def get_message_count(
        self, 
        db: AsyncSession, 
        conversation_id: str
    ) -> int:
        """获取会话的消息数量"""
        result = await db.execute(
            select(func.count(Message.id))
            .where(Message.conversation_id == conversation_id)
        )
        return result.scalar() or 0


class CRUDMessage:
    """消息CRUD操作"""
    
    async def get(
        self,
        db: AsyncSession,
        message_id: str
    ) -> Optional[Message]:
        """获取单个消息"""
        result = await db.execute(
            select(Message).where(Message.id == message_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_conversation(
        self, 
        db: AsyncSession, 
        conversation_id: str
    ) -> List[Message]:
        """获取会话的所有消息"""
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())
    
    async def create(
        self, 
        db: AsyncSession, 
        conversation_id: str,
        role: str,
        content: str,
        images: Optional[str] = None,
        cost_meta: Optional[str] = None,
        thinking: Optional[str] = None,
        extra: Optional[str] = None,
    ) -> Message:
        """创建消息"""
        message_id = str(uuid.uuid4())
        
        db_obj = Message(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            images=images,
            cost_meta=cost_meta,
            thinking=thinking,
            extra=extra,
        )
        db.add(db_obj)
        
        # 更新会话的updated_at
        await db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
        )
        
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    
    async def update(
        self,
        db: AsyncSession,
        message_id: str,
        obj_in: Message
    ) -> Optional[Message]:
        """更新消息"""
        db_obj = await self.get(db, message_id)
        if not db_obj:
            return None
        
        # 更新所有属性
        for field in ['content', 'retry_versions', 'role', 'images', 'cost_meta', 'thinking', 'extra']:
            if hasattr(obj_in, field):
                setattr(db_obj, field, getattr(obj_in, field))
        
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def set_extra(
        self,
        db: AsyncSession,
        message_id: str,
        extra: Optional[str],
    ) -> Optional[Message]:
        """更新消息 extra JSON 字符串。"""
        db_obj = await self.get(db, message_id)
        if not db_obj:
            return None
        db_obj.extra = extra
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    
    async def delete_by_conversation(
        self, 
        db: AsyncSession, 
        conversation_id: str
    ) -> bool:
        """删除会话的所有消息"""
        result = await db.execute(
            delete(Message).where(Message.conversation_id == conversation_id)
        )
        await db.commit()
        return result.rowcount > 0


# 创建实例
conversation_crud = CRUDConversation()
message_crud = CRUDMessage()
