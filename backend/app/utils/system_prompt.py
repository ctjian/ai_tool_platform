"""系统提示词工具"""
from typing import Iterable, Optional


DEFAULT_SYSTEM_PROMPT = """你在对话中应当表现得自然、清晰、有条理。

优先进行真正的交流，而不仅是给出答案。
在回答问题时，关注用户的意图、语气和上下文，并相应调整表达方式。

假设用户是理性且有理解能力的，不要居高临下，也不要过度简化。

使用结构化表达来提升可读性，但避免生硬或学术化的语气。

在适当的时候表现出理解、耐心和共情，但不要过度拟人或制造情绪。

当存在不确定性时，应坦诚说明；当无法满足请求时，应清晰、礼貌地拒绝，并提供最接近的替代帮助。

目标是让用户感到被认真对待，而不是被说服、被教育或被敷衍。"""


def get_default_system_prompt() -> str:
    return DEFAULT_SYSTEM_PROMPT


def pick_system_prompt(messages: Iterable) -> Optional[str]:
    """从消息里取最新的 system 提示词"""
    latest = None
    for msg in messages:
        if getattr(msg, "role", None) == "system":
            latest = msg
    if not latest:
        return None
    content = getattr(latest, "content", None) or ""
    content = content.strip()
    return content or None
