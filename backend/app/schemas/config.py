"""配置相关的Pydantic schemas"""
from pydantic import BaseModel, Field
from typing import Optional


class APIConfigResponse(BaseModel):
    """API配置响应（脱敏）"""
    api_key: str = Field(..., description="API Key（脱敏显示）")
    base_url: str = Field(..., description="API基础URL")
    model: str = Field(..., description="模型名称")
    temperature: float = Field(..., description="温度参数")
    max_tokens: int = Field(..., description="最大token数")
    top_p: float = Field(..., description="Top P参数")
    frequency_penalty: float = Field(..., description="频率惩罚")
    presence_penalty: float = Field(..., description="存在惩罚")


class APIConfigUpdate(BaseModel):
    """更新API配置"""
    api_key: Optional[str] = Field(None, min_length=1, description="OpenAI API Key")
    base_url: Optional[str] = Field(None, description="API基础URL")
    model: Optional[str] = Field(None, description="模型名称")
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, gt=0)
    top_p: Optional[float] = Field(None, ge=0, le=1)
    frequency_penalty: Optional[float] = Field(None, ge=-2, le=2)
    presence_penalty: Optional[float] = Field(None, ge=-2, le=2)


class TestConnectionRequest(BaseModel):
    """测试连接请求"""
    api_key: str = Field(..., min_length=1)
    base_url: str = Field(default="https://api.openai.com/v1")
    model: str = Field(default="gpt-4o-mini")


class TestConnectionResponse(BaseModel):
    """测试连接响应"""
    success: bool
    message: str
    model_info: Optional[dict] = None
