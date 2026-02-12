"""LLM translator for LaTeX chunks.

Review note:
- 只翻译正文语义，不允许改写 LaTeX 命令与公式环境。
- 支持并发与重试，适配长文档批量翻译。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional
import asyncio

from httpx import Timeout
from openai import AsyncOpenAI

from app.custom_tools.arxiv_translate.splitter import normalize_llm_translated_chunk


ProgressFn = Optional[Callable[[int, int], Awaitable[None]]]


@dataclass
class TranslatorConfig:
    api_key: str
    base_url: str
    model: str
    target_language: str = "中文"
    concurrency: int = 2
    timeout_sec: int = 120


def _build_messages(chunk: str, target_language: str, extra_instruction: str) -> List[dict]:
    more_requirement = (extra_instruction or "").strip()
    if more_requirement and not more_requirement.endswith(" "):
        more_requirement += " "
    target = (target_language or "").strip()
    if ("中文" in target) or (target.lower() in {"zh", "chinese"}):
        user_prompt = (
            "Below is a section from an English academic paper, translate it into Chinese. "
            + more_requirement
            + r"Do not modify any latex command such as \section, \cite, \begin, \item and equations. "
            + r"Answer me only with the translated text:"
            + f"\n\n{chunk}"
        )
    else:
        user_prompt = (
            f"Below is a section from an English academic paper, translate it into {target or 'the target language'}. "
            + more_requirement
            + r"Do not modify any latex command such as \section, \cite, \begin, \item and equations. "
            + r"Answer me only with the translated text:"
            + f"\n\n{chunk}"
        )
    return [
        {
            "role": "system",
            "content": "You are a professional translator.",
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]


async def _translate_one_chunk(
    client: AsyncOpenAI,
    *,
    chunk: str,
    cfg: TranslatorConfig,
    extra_instruction: str,
    retries: int = 3,
) -> str:
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = await client.chat.completions.create(
                model=cfg.model,
                messages=_build_messages(chunk, cfg.target_language, extra_instruction),
                temperature=0.0,
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("模型返回空文本。")
            return normalize_llm_translated_chunk(content)
        except Exception as exc:
            last_err = exc
            if attempt >= retries:
                break
            await asyncio.sleep(min(1.5 * attempt, 4))
    raise RuntimeError(f"翻译分片失败：{last_err}")


async def translate_chunks(
    chunks: List[str],
    cfg: TranslatorConfig,
    *,
    extra_instruction: str = "",
    on_progress: ProgressFn = None,
) -> List[str]:
    if not cfg.api_key:
        raise RuntimeError("缺少 API Key，无法执行论文翻译。")
    if not cfg.model:
        raise RuntimeError("缺少模型名，无法执行论文翻译。")
    if not chunks:
        return []

    client_kwargs = {
        "api_key": cfg.api_key,
        "timeout": Timeout(float(cfg.timeout_sec)),
    }
    if cfg.base_url:
        client_kwargs["base_url"] = cfg.base_url
    client = AsyncOpenAI(**client_kwargs)

    semaphore = asyncio.Semaphore(max(1, int(cfg.concurrency)))
    translated = [""] * len(chunks)
    done = 0
    total = len(chunks)
    done_lock = asyncio.Lock()

    async def worker(index: int, chunk: str) -> None:
        nonlocal done
        async with semaphore:
            result = await _translate_one_chunk(
                client,
                chunk=chunk,
                cfg=cfg,
                extra_instruction=extra_instruction,
            )
            translated[index] = result
        async with done_lock:
            done += 1
            if on_progress:
                await on_progress(done, total)

    await asyncio.gather(*(worker(i, c) for i, c in enumerate(chunks)))
    return translated
