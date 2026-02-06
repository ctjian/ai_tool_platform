"""会话模型"""
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class Conversation(Base):
    """对话会话表"""
    __tablename__ = "conversations"
    
    id = Column(String(50), primary_key=True)
    tool_id = Column(String(50), ForeignKey("tools.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)
    
    # 关系
    tool = relationship("Tool", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")
    
    def __repr__(self):
        return f"<Conversation {self.title}>"
