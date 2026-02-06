"""分类模型"""
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class Category(Base):
    """工具分类表"""
    __tablename__ = "categories"
    
    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    icon = Column(String(10), nullable=False)
    description = Column(String, nullable=True)
    order = Column(Integer, nullable=False, default=0, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # 关系
    tools = relationship("Tool", back_populates="category", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Category {self.name}>"
