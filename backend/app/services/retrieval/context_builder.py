"""Build LLM context text from ranked chunks."""

from __future__ import annotations

from typing import Dict, List


def build_context_text(
    ranked_items: List[Dict],
    max_chunks: int = 8,
    max_chars: int = 12000,
) -> str:
    """
    Build compact context block from ranked chunks.
    """
    if not ranked_items:
        return ""

    blocks: List[str] = []
    total = 0
    used = 0
    for item in ranked_items:
        if used >= max_chunks:
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
        if total + len(block) > max_chars:
            break
        blocks.append(block)
        total += len(block)
        used += 1

    return "\n".join(blocks).strip()

