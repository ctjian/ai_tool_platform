"""应用配置"""
from pydantic_settings import BaseSettings
from typing import List


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
    OPENAI_MODEL: str = "gpt-4o-mini"
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """获取CORS允许的源列表"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 全局配置实例
settings = Settings()
