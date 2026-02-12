"""Build section-first chunks from markdown."""

from __future__ import annotations

import hashlib
import re
from typing import Dict, List


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text or "")


def _token_count(text: str) -> int:
    return len(_tokenize(text))


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[。！？!?\.])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _split_markdown_sections(markdown: str) -> List[tuple[str, str]]:
    lines = markdown.splitlines()
    sections: List[tuple[str, str]] = []
    current_heading = "Body"
    buffer: List[str] = []

    def flush():
        nonlocal buffer, current_heading
        text = "\n".join(buffer).strip()
        if text:
            sections.append((current_heading, text))
        buffer = []

    for line in lines:
        if line.startswith("## "):
            flush()
            current_heading = line[3:].strip() or "Untitled"
        elif line.startswith("# "):
            # Title as metadata, do not chunk as body section
            continue
        else:
            buffer.append(line)
    flush()
    return sections


def _split_long_paragraph(paragraph: str, max_tokens: int, overlap_tokens: int) -> List[str]:
    sentences = _split_sentences(paragraph)
    if not sentences:
        return [paragraph]

    chunks: List[str] = []
    cur = ""
    for s in sentences:
        nxt = (cur + " " + s).strip() if cur else s
        if _token_count(nxt) <= max_tokens:
            cur = nxt
            continue
        if cur:
            chunks.append(cur)
        if _token_count(s) <= max_tokens:
            cur = s
            continue

        # Very long sentence: hard split by characters.
        step = max(200, max_tokens * 2)
        overlap_chars = max(40, overlap_tokens * 2)
        start = 0
        sent = s.strip()
        sent_len = len(sent)
        while start < sent_len:
            end = min(sent_len, start + step)
            chunks.append(sent[start:end].strip())
            if end >= sent_len:
                break
            start = max(0, end - overlap_chars)
        cur = ""

    if cur:
        chunks.append(cur)

    # Add overlap between adjacent sentence chunks.
    overlap_chars = max(40, overlap_tokens * 2)
    with_overlap: List[str] = []
    for i, text in enumerate(chunks):
        if i == 0:
            with_overlap.append(text)
            continue
        prefix = chunks[i - 1][-overlap_chars:].strip()
        if prefix:
            with_overlap.append((prefix + " " + text).strip())
        else:
            with_overlap.append(text)
    return with_overlap


def build_chunks_from_markdown(
    markdown: str,
    canonical_id: str,
    strategy: Dict[str, int],
) -> List[Dict]:
    """
    Section-first chunking with long-paragraph secondary split.
    """
    max_tokens = int(strategy.get("max_tokens", 1200))
    target_tokens = int(strategy.get("target_tokens", 900))
    overlap_tokens = int(strategy.get("overlap_tokens", 120))
    min_tokens = int(strategy.get("min_tokens", 120))

    sections = _split_markdown_sections(markdown)
    chunks: List[Dict] = []
    global_order = 1

    for sec_idx, (heading, sec_text) in enumerate(sections, start=1):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", sec_text) if p.strip()]
        if not paragraphs:
            continue

        local_parts: List[str] = []
        cur = ""
        for para in paragraphs:
            para_tokens = _token_count(para)
            if para_tokens > max_tokens:
                if cur:
                    local_parts.append(cur.strip())
                    cur = ""
                local_parts.extend(_split_long_paragraph(para, max_tokens=max_tokens, overlap_tokens=overlap_tokens))
                continue

            nxt = (cur + "\n\n" + para).strip() if cur else para
            if _token_count(nxt) <= target_tokens:
                cur = nxt
            else:
                if cur:
                    local_parts.append(cur.strip())
                cur = para
        if cur:
            local_parts.append(cur.strip())

        # Merge tiny fragments into previous chunk where possible.
        merged: List[str] = []
        for part in local_parts:
            if merged and _token_count(part) < min_tokens:
                merged[-1] = (merged[-1] + "\n\n" + part).strip()
            else:
                merged.append(part)

        for part_idx, part_text in enumerate(merged, start=1):
            token_count = _token_count(part_text)
            chunk_id = f"{canonical_id}_s{sec_idx}_{part_idx:04d}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "section_id": f"s{sec_idx}",
                    "order": global_order,
                    "heading_path": [heading],
                    "text": part_text,
                    "token_count": token_count,
                    "char_count": len(part_text),
                    "page_start": None,
                    "page_end": None,
                    "char_start": None,
                    "char_end": None,
                    "text_sha1": hashlib.sha1(part_text.encode("utf-8")).hexdigest(),
                }
            )
            global_order += 1

    return chunks
