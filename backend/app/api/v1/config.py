"""配置管理API"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.crud.config import config_crud
from app.schemas.config import (
    APIConfigResponse,
    APIConfigUpdate,
    TestConnectionRequest,
    TestConnectionResponse,
)
from app.utils.openai_helper import test_openai_connection
from app.config import settings
from app.custom_tools.arxiv_translate.defaults import (
    DEFAULT_CONCURRENCY,
    DEFAULT_TARGET_LANGUAGE,
    DEFAULT_TRANSLATE_MODEL,
)

router = APIRouter()

# API配置的键名
API_CONFIG_KEY = "api_config"


def mask_api_key(api_key: str) -> str:
    """脱敏显示API Key"""
    if not api_key or len(api_key) < 8:
        return "***"
    return f"{api_key[:3]}***{api_key[-4:]}"


@router.get("/default")
async def get_default_config():
    """获取后端默认配置（从.env读取）"""
    model_groups = list(settings.openai_models_grouped)
    models = list(settings.openai_models_list)
    if settings.proxy_enabled:
        # 让 chatgpt 分组排在最前面
        model_groups = list(settings.proxy_models_grouped) + model_groups
        models = list(settings.proxy_models_list) + models
    return {
        "has_api_key": bool(settings.OPENAI_API_KEY),
        "base_url": settings.OPENAI_BASE_URL,
        "models": models,
        "model_groups": model_groups,
        "custom_tool_defaults": {
            "arxiv_translate": {
                "target_language": DEFAULT_TARGET_LANGUAGE,
                "concurrency": DEFAULT_CONCURRENCY,
                "model": DEFAULT_TRANSLATE_MODEL,
            }
        },
    }


@router.get("", response_model=APIConfigResponse)
async def get_config(db: AsyncSession = Depends(get_session)):
    """获取API配置（API Key脱敏显示）"""
    config = await config_crud.get(db, API_CONFIG_KEY)
    
    if not config:
        # 返回默认配置
        default_config = {
            "api_key": "",
            "base_url": settings.OPENAI_BASE_URL,
            "model": "",
            "temperature": 0.7,
            "max_tokens": 2000,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        }
        return APIConfigResponse(**{
            **default_config,
            "api_key": mask_api_key(default_config["api_key"])
        })
    
    # 脱敏API Key
    config["api_key"] = mask_api_key(config.get("api_key", ""))
    
    return APIConfigResponse(**config)


@router.put("")
async def update_config(
    config_in: APIConfigUpdate,
    db: AsyncSession = Depends(get_session)
):
    """更新API配置"""
    # 获取现有配置
    existing_config = await config_crud.get(db, API_CONFIG_KEY)
    
    if existing_config:
        # 合并更新
        update_data = config_in.model_dump(exclude_unset=True)
        new_config = {**existing_config, **update_data}
    else:
        # 创建新配置
        new_config = {
            "api_key": config_in.api_key or "",
            "base_url": config_in.base_url or settings.OPENAI_BASE_URL,
            "model": config_in.model or "",
            "temperature": config_in.temperature if config_in.temperature is not None else 0.7,
            "max_tokens": config_in.max_tokens or 2000,
            "top_p": config_in.top_p if config_in.top_p is not None else 1.0,
            "frequency_penalty": config_in.frequency_penalty if config_in.frequency_penalty is not None else 0.0,
            "presence_penalty": config_in.presence_penalty if config_in.presence_penalty is not None else 0.0,
        }
    
    # 保存配置
    await config_crud.set(db, API_CONFIG_KEY, new_config)
    
    return {"success": True, "message": "配置已更新"}


@router.post("/test", response_model=TestConnectionResponse)
async def test_connection(request: TestConnectionRequest):
    """测试OpenAI API连接"""
    try:
        success, message, model_info = await test_openai_connection(
            request.api_key,
            request.base_url,
            request.model
        )
        
        return TestConnectionResponse(
            success=success,
            message=message,
            model_info=model_info
        )
    
    except Exception as e:
        return TestConnectionResponse(
            success=False,
            message=f"测试失败: {str(e)}",
            model_info=None
        )
