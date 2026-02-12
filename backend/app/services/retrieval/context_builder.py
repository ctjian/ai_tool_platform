"""Build LLM context text from ranked chunks.

Review note:
- 上下文按 paper 分组输出，确保多论文场景下每篇来源独立清晰。
- 每个 chunk 保留 chunk_id/section/score，便于调试与引用扩展。
"""

from __future__ import annotations

import re
from typing import Dict, List


def _token_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text or ""))


def build_context_text(
    ranked_items: List[Dict],
    max_chunks: int | None = 8,
    max_tokens: int = 4000,
) -> str:
    """
    Build compact context block from ranked chunks.
    """
    if not ranked_items:
        return ""

    grouped: Dict[str, Dict] = {}
    paper_order: List[str] = []
    for item in ranked_items:
        chunk = item["chunk"]
        paper_id = str(chunk.get("paper_id") or "")
        canonical_id = str(chunk.get("paper_canonical_id") or "")
        group_key = paper_id or canonical_id or "unknown"
        if group_key not in grouped:
            grouped[group_key] = {
                "paper_id": paper_id,
                "canonical_id": canonical_id,
                "filename": chunk.get("paper_filename"),
                "title": (chunk.get("paper_title") or "").strip(),
                "items": [],
            }
            paper_order.append(group_key)
        grouped[group_key]["items"].append(item)

    blocks: List[str] = []
    total_tokens = 0
    used = 0
    for group_key in paper_order:
        paper = grouped[group_key]
        paper_id = paper.get("paper_id") or paper.get("canonical_id") or "unknown"
        filename = paper.get("filename") or paper.get("canonical_id") or "unknown.pdf"
        title = paper.get("title") or ""
        paper_header = f"[paper arxiv:{paper_id}] {filename}"
        if title:
            paper_header += f" | title={title}"

        paper_header_block = f"{paper_header}\n"
        paper_header_tokens = _token_count(paper_header_block)
        if total_tokens + paper_header_tokens > max_tokens:
            break
        blocks.append(paper_header_block)
        total_tokens += paper_header_tokens

        for item in paper["items"]:
            if max_chunks is not None and used >= max_chunks:
                break
            chunk = item["chunk"]
            score = float(item["score"])
            heading = " > ".join(chunk.get("heading_path") or [])
            block = (
                f"[chunk_id={chunk.get('chunk_id')} | section={heading} | score={score:.4f}]\n"
                f"{chunk.get('text', '').strip()}\n"
            )
            if not block.strip():
                continue
            block_tokens = _token_count(block)
            if total_tokens + block_tokens > max_tokens:
                break
            blocks.append(block)
            total_tokens += block_tokens
            used += 1
        if max_chunks is not None and used >= max_chunks:
            break

        # paper 间空行分隔
        if total_tokens < max_tokens:
            sep_tokens = _token_count("\n")
            if total_tokens + sep_tokens <= max_tokens:
                blocks.append("")
                total_tokens += sep_tokens

    return "\n".join(blocks).strip()
