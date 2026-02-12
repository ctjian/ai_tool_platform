"""会话模型

Review note:
- 使用 `extra` (TEXT JSON) 保存会话级可扩展状态（如 paper registry / active ids）。
- 固定列保持精简，后续需求尽量走 `extra`，避免频繁改表。
"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class Conversation(Base):
    """对话会话表"""
    __tablename__ = "conversations"
    
    id = Column(String(50), primary_key=True)
    tool_id = Column(String(50), ForeignKey("tools.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    extra = Column(Text, nullable=True, default=None)  # JSON string for extensible conversation state
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)
    
    # 关系
    tool = relationship("Tool", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")
    
    def __repr__(self):
        return f"<Conversation {self.title}>"
