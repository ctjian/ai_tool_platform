"""会话相关的Pydantic schemas"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


class MessageBase(BaseModel):
    """消息基础模型"""
    role: str = Field(..., description="角色: user, assistant, system")
    content: str = Field(..., min_length=1, description="消息内容")
    images: Optional[List[str]] = Field(None, description="图片数组（base64编码）")


class MessageCreate(MessageBase):
    """创建消息"""
    conversation_id: str = Field(..., description="所属会话ID")


class MessageResponse(MessageBase):
    """消息响应"""
    id: str
    conversation_id: str
    created_at: datetime
    retry_versions: Optional[List[str]] = Field(None, description="重试版本列表（之前的回复）")
    cost_meta: Optional[dict] = Field(None, description="计费信息")
    
    class Config:
        from_attributes = True

    @field_validator("cost_meta", mode="before")
    @classmethod
    def parse_cost_meta(cls, v):
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                import json
                return json.loads(v)
            except Exception:
                return None
        return None


class ConversationBase(BaseModel):
    """会话基础模型"""
    tool_id: Optional[str] = Field(None, description="关联的工具ID，为空时为通用对话模式")
    title: str = Field(..., min_length=1, max_length=200, description="会话标题")


class ConversationCreate(BaseModel):
    """创建会话"""
    tool_id: Optional[str] = Field(None, description="关联的工具ID，为空时为通用对话模式")


class ConversationUpdate(BaseModel):
    """更新会话"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    """会话响应（不含消息）"""
    id: str
    tool_id: Optional[str]
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = Field(default=0, description="消息数量")
    
    class Config:
        from_attributes = True


class ConversationDetailResponse(ConversationResponse):
    """会话详情响应（含消息）"""
    messages: list[MessageResponse] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    """会话列表响应"""
    conversations: list[ConversationResponse]


class ExportConversationResponse(BaseModel):
    """导出会话响应"""
    markdown: str = Field(..., description="Markdown格式的对话内容")
