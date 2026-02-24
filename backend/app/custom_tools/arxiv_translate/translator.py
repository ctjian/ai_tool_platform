"""LLM translator for LaTeX chunks.

Review note:
- 只翻译正文语义，不允许改写 LaTeX 命令与公式环境。
- 支持并发与重试，适配长文档批量翻译。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional, Tuple
import asyncio
from difflib import SequenceMatcher
import re

from httpx import Timeout
from openai import AsyncOpenAI

from app.custom_tools.arxiv_translate.splitter import normalize_llm_translated_chunk


ProgressFn = Optional[Callable[[int, int], Awaitable[None]]]
UsageFn = Optional[Callable[[Dict[str, int]], Awaitable[None]]]

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_EN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_WS_RE = re.compile(r"\s+")


@dataclass
class TranslatorConfig:
    api_key: str
    base_url: str
    model: str
    target_language: str = "中文"
    concurrency: int = 2
    timeout_sec: int = 120


def _is_chinese_target(target_language: str) -> bool:
    target = (target_language or "").strip().lower()
    return ("中文" in target) or (target in {"zh", "chinese"})


def _append_instruction(base: str, extra: str) -> str:
    head = (base or "").strip()
    tail = (extra or "").strip()
    if not head:
        return tail
    if not tail:
        return head
    return f"{head} {tail}"


def _looks_like_untranslated_chunk(original: str, translated: str, *, target_language: str) -> bool:
    if not _is_chinese_target(target_language):
        return False

    src = _WS_RE.sub(" ", (original or "").strip())
    out = _WS_RE.sub(" ", (translated or "").strip())
    if not src or not out:
        return False

    # Focus on prose chunks; short/math-heavy chunks are allowed to stay unchanged.
    if len(_EN_WORD_RE.findall(src)) < 10:
        return False
    if len(_CJK_RE.findall(out)) >= 6:
        return False

    if out == src:
        return True

    return SequenceMatcher(None, src, out).ratio() >= 0.97


def _build_messages(chunk: str, target_language: str, extra_instruction: str) -> List[dict]:
    more_requirement = (extra_instruction or "").strip()
    if more_requirement and not more_requirement.endswith(" "):
        more_requirement += " "
    target = (target_language or "").strip()
    if _is_chinese_target(target):
        user_prompt = (
            "Below is a section from an English academic paper, translate it into Chinese. "
            + more_requirement
            + r"Do not modify any LaTeX commands or environments (e.g., \section, \subsection, \subsubsection, \label, \ref, \eqref, \autoref, \cite, \begin{...}, \end{...}, \item, \caption) or any math content ($...$, \( ... \), \[ ... \], $$...$$). "
            + r"Translate all natural-language text, including text inside formatting commands such as \textit{...}, \textbf{...}, \emph{...}, and plain text after commands like \label{...}. "
            + r"Keep all numbers, percentages, units, and variable symbols unchanged."
            + r"Keep model names and benchmark names in English (e.g., GPT, Llama, MMLU, HellaSwag)."
            + r"Use formal and concise academic Chinese; avoid colloquial wording."
            + r"Answer me only with the translated text, without adding any explanation or extra content."
            + f"\n\n{chunk}"
        )
    else:
        user_prompt = (
            f"Below is a section from an English academic paper, translate it into {target or 'the target language'}. "
            + more_requirement
            + r"Do not modify any LaTeX commands or environments (e.g., \section, \subsection, \subsubsection, \label, \ref, \eqref, \autoref, \cite, \begin{...}, \end{...}, \item, \caption) or any math content ($...$, \( ... \), \[ ... \], $$...$$). "
            + r"Answer me only with the translated text, without adding any explanation or extra content."
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
    retries: int = 2,
) -> Tuple[str, Optional[Dict[str, int]]]:
    for attempt in range(1, retries + 1):
        try:
            attempt_instruction = extra_instruction
            if attempt > 1 and _is_chinese_target(cfg.target_language):
                attempt_instruction = _append_instruction(
                    extra_instruction,
                    r"Do not leave full English sentences unchanged. Translate all prose, including text inside \textit{...}, \textbf{...}, \emph{...}, and text after \label{...}.",
                )
            resp = await client.chat.completions.create(
                model=cfg.model,
                messages=_build_messages(chunk, cfg.target_language, attempt_instruction),
                temperature=0.0,
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("模型返回空文本。")
            normalized = normalize_llm_translated_chunk(content)
            if _looks_like_untranslated_chunk(chunk, normalized, target_language=cfg.target_language):
                raise RuntimeError("模型返回疑似未翻译文本。")
            usage_obj = getattr(resp, "usage", None)
            usage: Optional[Dict[str, int]] = None
            if usage_obj is not None:
                usage = {
                    "prompt_tokens": int(getattr(usage_obj, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage_obj, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(usage_obj, "total_tokens", 0) or 0),
                }
            return normalized, usage
        except asyncio.CancelledError:
            raise
        except Exception:
            if attempt >= retries:
                break
            await asyncio.sleep(min(1.5 * attempt, 4))
    # Retry once and then fall back to original chunk so a single gateway error
    # does not fail the whole translation job.
    return chunk, None


async def translate_chunks(
    chunks: List[str],
    cfg: TranslatorConfig,
    *,
    extra_instruction: str = "",
    on_progress: ProgressFn = None,
    on_usage: UsageFn = None,
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
            result, usage = await _translate_one_chunk(
                client,
                chunk=chunk,
                cfg=cfg,
                extra_instruction=extra_instruction,
            )
            translated[index] = result
            if on_usage and usage is not None:
                await on_usage(usage)
        async with done_lock:
            done += 1
            if on_progress:
                await on_progress(done, total)

    await asyncio.gather(*(worker(i, c) for i, c in enumerate(chunks)))
    return translated
