"""Chat2API 代理辅助函数"""
from typing import AsyncGenerator, Dict, Any, Optional
import json
import httpx


async def stream_chat2api_completion(
    base_url: str,
    access_token: str,
    model: str,
    messages: list[dict],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    top_p: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    presence_penalty: Optional[float] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """调用 Chat2API 代理的流式接口（OpenAI 兼容）"""
    if not access_token:
        yield {"type": "error", "error": "未配置 ACCESS_TOKEN"}
        return
    if not base_url:
        yield {"type": "error", "error": "未配置 PROXY_BASE_URL"}
        return

    url = base_url.rstrip("/") + "/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if top_p is not None:
        payload["top_p"] = top_p
    if frequency_penalty is not None:
        payload["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        payload["presence_penalty"] = presence_penalty

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    timeout = httpx.Timeout(60.0, read=None)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                yield {"type": "error", "error": f"Chat2API 错误: {resp.status_code} {text.decode(errors='ignore')}"}
                return

            async for line in resp.aiter_lines():
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except Exception:
                    continue

                choices = data.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    if "content" in delta and delta["content"] is not None:
                        yield {"type": "token", "content": delta["content"]}
                    reasoning = (
                        delta.get("reasoning_content")
                        or delta.get("reasoning")
                        or delta.get("thinking")
                    )
                    if reasoning:
                        yield {"type": "thinking", "content": reasoning}

                usage = data.get("usage")
                if usage and usage.get("total_tokens") is not None:
                    yield {"type": "usage", "usage": usage}
