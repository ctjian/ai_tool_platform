"""会话相关的Pydantic schemas

Review note:
- `extra` 字段承载可扩展 JSON（会话/消息维度）。
- 前端按字典读取，不耦合固定子字段。
"""
from pydantic import BaseModel, Field, field_validator, ConfigDict
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
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    created_at: datetime
    retry_versions: Optional[List[str]] = Field(None, description="重试版本列表（之前的回复）")
    cost_meta: Optional[dict] = Field(None, description="计费信息")
    thinking: Optional[str] = Field(None, description="模型思考内容")
    extra: Optional[dict] = Field(None, description="消息扩展元数据")
    
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

    @field_validator("extra", mode="before")
    @classmethod
    def parse_extra(cls, v):
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
    system_prompt: Optional[str] = Field(None, description="系统提示词（写入到 system 消息）")


class ConversationResponse(BaseModel):
    """会话响应（不含消息）"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    tool_id: Optional[str]
    title: str
    extra: Optional[dict] = Field(None, description="会话扩展元数据")
    created_at: datetime
    updated_at: datetime
    message_count: int = Field(default=0, description="消息数量")

    @field_validator("extra", mode="before")
    @classmethod
    def parse_conversation_extra(cls, v):
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


class ConversationDetailResponse(ConversationResponse):
    """会话详情响应（含消息）"""
    model_config = ConfigDict(from_attributes=True)

    messages: list[MessageResponse] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    """会话列表响应"""
    conversations: list[ConversationResponse]


class ExportConversationResponse(BaseModel):
    """导出会话响应"""
    markdown: str = Field(..., description="Markdown格式的对话内容")
