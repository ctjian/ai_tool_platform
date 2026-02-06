"""配置模型"""
from sqlalchemy import Column, String, Text, DateTime
from datetime import datetime

from app.models.base import Base


class Config(Base):
    """配置表"""
    __tablename__ = "config"
    
    key = Column(String(50), primary_key=True)
    value = Column(Text, nullable=False)  # JSON格式存储
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<Config {self.key}>"
