"""应用配置"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
from pathlib import Path


class Settings(BaseSettings):
    """应用配置类"""

    # 应用信息
    APP_NAME: str = "AI工具平台"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # 数据库配置
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/ai_tools.db"
    CHAT_DATABASE_URL: str = "sqlite+aiosqlite:///./data/chat_history.db"  # 对话历史单独数据库
    
    # CORS配置
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:20102,http://localhost:5174"
    
    # 文件上传配置
    MAX_UPLOAD_SIZE: int = 2097152  # 2MB
    UPLOAD_DIR: str = "./uploads"
    ALLOWED_EXTENSIONS: List[str] = ["jpg", "jpeg", "png", "svg"]
    
    # OpenAI默认配置（可选，优先使用UI配置）
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.yunwu.ai/v1"
    TITLE_MODEL: str = Field("gpt-4o-mini", validation_alias="Title_MODEL")
    # 逗号分隔模型，分组用 ;，格式：Group:model1,model2;Group2:model3
    OPENAI_MODELS: str = "OpenAI:gpt-4o-mini,gpt-4o"

    # 计费配置
    PRICING_FILE: str = str(Path(__file__).resolve().parents[1] / "data" / "pricing.json")
    PRICE_INPUT_PER_1M: float = 2.0  # 基础输入价格（美元/1M tokens）
    PRICE_GROUP_RATIO: float = 1.5  # 分组倍率
    PRICE_CURRENCY: str = "USD"
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """获取CORS允许的源列表"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def openai_models_grouped(self) -> List[dict]:
        """获取可选模型分组列表"""
        groups = []
        for group_chunk in self.OPENAI_MODELS.split(";"):
            chunk = group_chunk.strip()
            if not chunk:
                continue
            if ":" not in chunk:
                # 兜底：无分组名，放入默认组
                groups.append({"name": "Default", "models": [m.strip() for m in chunk.split(",") if m.strip()]})
                continue
            name, models_str = chunk.split(":", 1)
            models = [m.strip() for m in models_str.split(",") if m.strip()]
            if models:
                groups.append({"name": name.strip(), "models": models})
        return groups

    @property
    def openai_models_list(self) -> List[str]:
        """获取可选模型列表（扁平）"""
        flat = []
        for g in self.openai_models_grouped:
            flat.extend(g["models"])
        return flat

    
    class Config:
        env_file = (".env", "backend/.env")
        case_sensitive = True
        extra = "ignore"


# 全局配置实例
settings = Settings()
