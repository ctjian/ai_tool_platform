"""应用配置"""
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
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
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:2102,http://localhost:5174"
    
    # 文件上传配置
    MAX_UPLOAD_SIZE: int = 2097152  # 2MB
    UPLOAD_DIR: str = "./uploads"
    ALLOWED_EXTENSIONS: List[str] = ["jpg", "jpeg", "png", "svg"]
    CHAT_MAX_PDF_FILES: int = 5
    CHAT_MAX_PDF_SIZE_MB: int = 20
    
    # OpenAI默认配置（可选，优先使用UI配置）
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.yunwu.ai/v1"
    TITLE_MODEL: str = Field("gpt-4o-mini", validation_alias="Title_MODEL")
    OPENAI_TIMEOUT_SEC: int = 60

    # 计费配置
    PRICING_FILE: str = str(Path(__file__).resolve().parents[1] / "data" / "pricing.json")
    PRICE_INPUT_PER_1M: float = 2.0  # 基础输入价格（美元/1M tokens）
    PRICE_GROUP_RATIO: float = 1.5  # 分组倍率
    PRICE_CURRENCY: str = "USD"
    
    # 论文解析（arXiv + GROBID）
    GROBID_URLS: str = "https://lfoppiano-grobid.hf.space"
    PAPER_DATA_DIR: str = str(Path(__file__).resolve().parents[1] / "data" / "chat" / "papers")
    ARXIV_MAX_ACTIVE_PAPERS: int = 3
    ARXIV_CONTEXT_TOP_K: int = 8
    ARXIV_CONTEXT_MAX_TOKENS: int = 4000
    ARXIV_LOW_SCORE_FULLTEXT_THRESHOLD: float = 0.55
    ARXIV_DOWNLOAD_TIMEOUT_SEC: int = 30
    GROBID_TIMEOUT_SEC: int = 120
    ARXIV_CHUNK_TARGET_TOKENS: int = 900
    ARXIV_CHUNK_MAX_TOKENS: int = 1200
    ARXIV_CHUNK_OVERLAP_TOKENS: int = 120
    ARXIV_CHUNK_MIN_TOKENS: int = 120
    ARXIV_QUERY_REWRITE_MODEL: str = "gpt-4o-mini"
    ARXIV_QUERY_REWRITE_HISTORY_TURNS: int = 3
    ARXIV_QUERY_REWRITE_ABSTRACT_CHARS: int = 1200
    ARXIV_QUERY_REWRITE_TIMEOUT_SEC: int = 30

    # Embedding 检索（SiliconFlow）
    EMBEDDING_BASE_URL: str = "https://api.siliconflow.cn/v1"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "Pro/BAAI/bge-m3"
    EMBEDDING_TIMEOUT_SEC: int = 60
    EMBEDDING_BATCH_SIZE: int = 16

    # AI Notebook（Markdown 笔记 + 向量检索）
    NOTEBOOK_DATA_DIR: str = str(Path(__file__).resolve().parents[1] / "data" / "notebook" / "notes")
    NOTEBOOK_CONTEXT_MAX_TOKENS: int = 3200
    NOTEBOOK_MAX_NOTES_PER_QUERY: int = 4
    NOTEBOOK_MAX_CHUNKS_PER_NOTE: int = 3

    # 自定义工具：arXiv LaTeX 精细翻译
    CUSTOM_TOOLS_DATA_DIR: str = str(Path(__file__).resolve().parents[1] / "data" / "custom_tools")
    ARXIV_TRANSLATE_DATA_DIR: str = str(
        Path(__file__).resolve().parents[1] / "data" / "custom_tools" / "arxiv_translate"
    )

    @model_validator(mode="before")
    @classmethod
    def treat_empty_env_as_unset(cls, data):
        """
        将空字符串环境变量按“未配置”处理。
        这样 .env 中留空不会覆盖默认值，也避免复杂类型解析报错。
        """
        if not isinstance(data, dict):
            return data

        cleaned = dict(data)
        for field_name, field in cls.model_fields.items():
            default = field.default

            # 仅当字段本身有可用默认值时，空字符串才回退到默认值
            if default in (None, ""):
                continue

            keys = {field_name}
            alias = field.validation_alias
            if isinstance(alias, str):
                keys.add(alias)

            for key in keys:
                if cleaned.get(key) == "":
                    cleaned.pop(key, None)

        return cleaned
    
    @property
    def cors_origins_list(self) -> List[str]:
        """获取CORS允许的源列表"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def grobid_urls_list(self) -> List[str]:
        """获取 GROBID 服务列表（按配置顺序）。"""
        urls: List[str] = []
        seen = set()
        for part in str(self.GROBID_URLS or "").split(","):
            url = part.strip().rstrip("/")
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

    
    class Config:
        env_file = (".env", "backend/.env")
        case_sensitive = True
        extra = "ignore"


# 全局配置实例
settings = Settings()
