"""消息模型"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class Message(Base):
    """消息表"""
    __tablename__ = "messages"
    
    id = Column(String(50), primary_key=True)
    conversation_id = Column(String(50), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    images = Column(Text, nullable=True, default=None)  # JSON array of base64 images
    retry_versions = Column(Text, nullable=True, default=None)  # JSON array of previous assistant responses (for retry functionality)
    cost_meta = Column(Text, nullable=True, default=None)  # JSON string for cost metadata
    thinking = Column(Text, nullable=True, default=None)  # Model thinking/reasoning content
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # 关系
    conversation = relationship("Conversation", back_populates="messages")
    
    # 约束
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="check_role"),
    )
    
    def __repr__(self):
        return f"<Message {self.role}: {self.content[:50]}...>"
