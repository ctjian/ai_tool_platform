"""OpenAI辅助函数"""
from openai import AsyncOpenAI
from typing import AsyncGenerator, Dict, Any
import json
from httpx import Timeout

from app.schemas.chat import APIConfig
from app.config import settings


async def stream_chat_completion(
    api_config: APIConfig,
    messages: list[dict],
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    流式调用OpenAI Chat Completion API
    
    Args:
        api_config: API配置
        messages: 消息列表
    
    Yields:
        生成的文本内容（逐token）
    """
    # 初始化客户端时只传递必要参数
    api_key = api_config.api_key or settings.OPENAI_API_KEY
    if not api_key:
        yield json.dumps({"error": "未配置API Key"})
        return

    client_kwargs = {
        "api_key": api_key,
        "timeout": Timeout(15.0),  # 15秒超时
    }
    
    # 如果提供了base_url，设置它
    if api_config.base_url:
        client_kwargs["base_url"] = api_config.base_url
    
    client = AsyncOpenAI(**client_kwargs)
    
    try:
        try:
            stream = await client.chat.completions.create(
                model=api_config.model,
                messages=messages,
                temperature=api_config.temperature,
                max_tokens=api_config.max_tokens,
                top_p=api_config.top_p,
                frequency_penalty=api_config.frequency_penalty,
                presence_penalty=api_config.presence_penalty,
                stream=True,
                stream_options={"include_usage": True},
            )
        except TypeError as e:
            # 兼容旧版本 openai SDK：不支持 stream_options
            if "stream_options" not in str(e):
                raise
            stream = await client.chat.completions.create(
                model=api_config.model,
                messages=messages,
                temperature=api_config.temperature,
                max_tokens=api_config.max_tokens,
                top_p=api_config.top_p,
                frequency_penalty=api_config.frequency_penalty,
                presence_penalty=api_config.presence_penalty,
                stream=True,
            )
        
        async for chunk in stream:
            # 检查chunk是否有choices且不为空
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield {"type": "token", "content": delta.content}
            usage = getattr(chunk, "usage", None)
            if usage and getattr(usage, "total_tokens", None):
                if hasattr(usage, "model_dump"):
                    usage_data = usage.model_dump()
                else:
                    usage_data = dict(usage)
                yield {"type": "usage", "usage": usage_data}
    
    except Exception as e:
        error_msg = f"OpenAI API错误: {str(e)}"
        yield {"type": "error", "error": error_msg}


async def test_openai_connection(
    api_key: str,
    base_url: str,
    model: str
) -> tuple[bool, str, dict]:
    """
    测试OpenAI API连接
    
    Returns:
        (是否成功, 消息, 模型信息)
    """
    client_kwargs = {
        "api_key": api_key,
        "timeout": Timeout(15.0),  # 15秒超时
    }
    
    # 如果提供了base_url，设置它
    if base_url:
        client_kwargs["base_url"] = base_url
    
    client = AsyncOpenAI(**client_kwargs)
    
    try:
        # 发送一个简单的测试请求
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=5,
        )
        
        return (
            True,
            "连接成功",
            {
                "model": response.model,
                "available": True,
            }
        )
    
    except Exception as e:
        return (
            False,
            f"连接失败: {str(e)}",
            None
        )


async def generate_title_for_conversation(messages: list, api_config=None) -> str:
    """
    根据对话消息自动生成标题
    
    Args:
        messages: 消息列表
        api_config: OpenAI API 配置（可选），包含 api_key, base_url, model 等
    
    Returns:
        生成的标题
    """
    from app.models.message import Message
    
    # 找到第一条用户消息和第一条助手消息
    user_message = None
    assistant_message = None
    
    for msg in messages:
        if isinstance(msg, Message):
            if msg.role == 'user' and not user_message:
                user_message = msg.content
            elif msg.role == 'assistant' and not assistant_message:
                assistant_message = msg.content
        else:
            # 字典格式
            if msg.get('role') == 'user' and not user_message:
                user_message = msg.get('content', '')
            elif msg.get('role') == 'assistant' and not assistant_message:
                assistant_message = msg.get('content', '')
    
    if not user_message:
        return "新对话"
    
    # 优先使用传入的 api_config（UI配置），如果没有则使用 .env 配置
    if api_config:
        # 从 api_config 字典或对象中获取
        if isinstance(api_config, dict):
            api_key = api_config.get('api_key')
            base_url = api_config.get('base_url')
            model = api_config.get('model') or ""
        else:
            api_key = getattr(api_config, 'api_key', None)
            base_url = getattr(api_config, 'base_url', None)
            model = getattr(api_config, 'model', "") or ""
    else:
        # 如果没有UI配置，则读取 .env 中的配置
        api_key = settings.OPENAI_API_KEY or None
        base_url = settings.OPENAI_BASE_URL
        model = ""
    
    if not api_key:
        # 如果没有配置API key，使用用户消息的前10个字作为标题
        return user_message[:10].strip() + ("..." if len(user_message) > 10 else "")
    
    # 构建消息用于生成标题
    title_prompt = f"""请根据以下对话生成一个简短的标题（5-10个字），直接返回标题，不要加引号和其他说明。

用户消息: {user_message[:200]}

助手回复: {(assistant_message or '')[:200]}

标题:"""
    
    # 使用标题专用模型（如未设置则回退到当前模型）
    title_model = settings.TITLE_MODEL or model
    
    client_kwargs = {
        "api_key": api_key,
        "timeout": Timeout(15.0),
    }
    
    if base_url:
        client_kwargs["base_url"] = base_url
    
    client = AsyncOpenAI(**client_kwargs)
    
    try:
        response = await client.chat.completions.create(
            model=title_model,
            messages=[
                {"role": "user", "content": title_prompt}
            ],
            max_tokens=50,
            temperature=0.5,
        )
        
        title = response.choices[0].message.content.strip()
        # 移除可能的引号
        title = title.strip('"\'')
        return title if title else "新对话"
    
    except Exception as e:
        print(f"生成标题失败: {str(e)}")
        # 如果生成失败，使用用户消息的前10个字作为标题
        return user_message[:10].strip() + ("..." if len(user_message) > 10 else "")
