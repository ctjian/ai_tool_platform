"""工具模型"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class Tool(Base):
    """工具表"""
    __tablename__ = "tools"
    
    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False, index=True)
    category_id = Column(String(50), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True)
    icon = Column(String(500), nullable=False)  # emoji或图片URL
    icon_type = Column(String(20), default='emoji', nullable=False)  # emoji或image
    description = Column(Text, nullable=False)
    system_prompt = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # 关系
    category = relationship("Category", back_populates="tools")
    conversations = relationship("Conversation", back_populates="tool", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Tool {self.name}>"
