"""聊天相关的Pydantic schemas"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict


class APIConfig(BaseModel):
    """OpenAI API配置"""
    # api_key 允许为空；后端会在需要时回退到 .env 配置
    api_key: str = Field(default="", description="OpenAI API Key")
    base_url: str = Field(default="https://api.openai.com/v1", description="API基础URL")
    model: str = Field(default="gpt-4o-mini", description="模型名称")
    temperature: float = Field(default=0.7, ge=0, le=2, description="温度参数")
    max_tokens: int = Field(default=2000, gt=0, description="最大token数")
    top_p: float = Field(default=1.0, ge=0, le=1, description="Top P参数")
    frequency_penalty: float = Field(default=0.0, ge=-2, le=2, description="频率惩罚")
    presence_penalty: float = Field(default=0.0, ge=-2, le=2, description="存在惩罚")


class ChatRequest(BaseModel):
    """聊天请求"""
    conversation_id: str = Field(..., description="会话ID")
    tool_id: Optional[str] = Field(None, description="工具ID，为空时使用默认系统提示词")
    message: str = Field(..., min_length=1, description="用户消息")
    images: Optional[List[str]] = Field(None, description="图片base64列表")
    api_config: APIConfig = Field(..., description="API配置")
    context_rounds: Optional[int] = Field(
        None,
        ge=5,
        le=20,
        description="上下文轮数（保留最近N轮用户对话）",
    )
    retry_message_id: Optional[str] = Field(None, description="重试的消息ID（如果是重试操作）")
    selected_versions: Optional[Dict[str, int]] = Field(None, description="每条消息选中的版本索引（message_id -> version_index）")


class StopChatRequest(BaseModel):
    """停止聊天请求"""
    conversation_id: str = Field(..., description="会话ID")
