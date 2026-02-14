"""Notebook storage and retrieval services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import json
import logging
import re
import secrets
import shutil
import time

from app.services.retrieval.chunker import build_chunks_from_markdown
from app.services.retrieval.embedding_client import (
    EmbeddingClient,
    EmbeddingConfigError,
    EmbeddingServiceError,
)
from app.services.retrieval.ranker import rank_chunks

logger = logging.getLogger("uvicorn.error")

CONTENT_ENDPOINT_PREFIX = "/api/v1/notebook/notes"


class NotebookServiceError(RuntimeError):
    """Expected notebook service error."""


class NotebookNotFoundError(NotebookServiceError):
    """Raised when notebook note is not found."""


@dataclass(frozen=True)
class NotebookNotePaths:
    root_dir: Path
    note_dir: Path
    markdown_path: Path
    chunks_path: Path
    embeddings_path: Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _token_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text or ""))


def _normalize_id(raw: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "").strip().lower()).strip("-")
    return value[:64]


def _normalize_tags(tags: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in tags:
        tag = str(item or "").strip()
        if not tag:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag[:30])
    return out


def _strip_markdown_text(text: str) -> str:
    return " ".join(
        re.sub(r"[#>*`~\[\]\(\)\-]", " ", str(text or ""))
        .replace("\r", "\n")
        .split()
    )


def _safe_summary(summary: str, content: str) -> str:
    picked = str(summary or "").strip()
    if picked:
        return picked[:200]
    return _strip_markdown_text(content)[:160]


def _build_snippet(text: str, limit: int = 180) -> str:
    plain = _strip_markdown_text(text)
    if len(plain) <= limit:
        return plain
    return f"{plain[:limit].rstrip()}..."


def _note_paths(settings, note_id: str) -> NotebookNotePaths:
    root_dir = Path(settings.NOTEBOOK_DATA_DIR).resolve()
    note_dir = root_dir / note_id
    return NotebookNotePaths(
        root_dir=root_dir,
        note_dir=note_dir,
        markdown_path=note_dir / "note.md",
        chunks_path=note_dir / "chunks.jsonl",
        embeddings_path=note_dir / "chunk_embeddings.json",
    )


def _index_path(settings) -> Path:
    return Path(settings.NOTEBOOK_DATA_DIR).resolve() / "index.json"


def _read_index(settings) -> List[Dict]:
    index_path = _index_path(settings)
    if not index_path.exists():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    normalized: List[Dict] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        note_id = _normalize_id(item.get("id") or "")
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        normalized.append(
            {
                "id": note_id,
                "title": str(item.get("title") or "").strip()[:200] or note_id,
                "tags": _normalize_tags(item.get("tags") or []),
                "updated_at": str(item.get("updated_at") or "").strip() or _now_date(),
                "summary": str(item.get("summary") or "").strip()[:500],
            }
        )
    return normalized


def _write_index(settings, notes: List[Dict]) -> None:
    root_dir = Path(settings.NOTEBOOK_DATA_DIR).resolve()
    root_dir.mkdir(parents=True, exist_ok=True)
    index_path = _index_path(settings)
    index_path.write_text(
        json.dumps(notes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _seed_notes_dir() -> Path:
    # backend/app/services/notebook/notebook_service.py -> project root
    project_root = Path(__file__).resolve().parents[4]
    return project_root / "frontend" / "public" / "notebook" / "notes"


def ensure_notebook_store(settings) -> None:
    root_dir = Path(settings.NOTEBOOK_DATA_DIR).resolve()
    root_dir.mkdir(parents=True, exist_ok=True)

    existing = _read_index(settings)
    if existing:
        return

    seed_dir = _seed_notes_dir()
    seed_index = seed_dir / "index.json"
    seeded_notes: List[Dict] = []
    seen: set[str] = set()
    if not seed_index.exists():
        _write_index(settings, [])
        return

    try:
        payload = json.loads(seed_index.read_text(encoding="utf-8"))
    except Exception:
        _write_index(settings, [])
        return
    if not isinstance(payload, list):
        _write_index(settings, [])
        return

    for item in payload:
        if not isinstance(item, dict):
            continue
        note_id = _normalize_id(item.get("id") or "")
        if not note_id or note_id in seen:
            continue
        rel_path = str(item.get("path") or "").strip()
        filename = Path(rel_path).name
        source_md = seed_dir / filename
        if not source_md.exists():
            continue
        note_paths = _note_paths(settings, note_id)
        note_paths.note_dir.mkdir(parents=True, exist_ok=True)
        note_paths.markdown_path.write_text(source_md.read_text(encoding="utf-8"), encoding="utf-8")
        seen.add(note_id)
        seeded_notes.append(
            {
                "id": note_id,
                "title": str(item.get("title") or "").strip()[:200] or note_id,
                "tags": _normalize_tags(item.get("tags") or []),
                "updated_at": str(item.get("updated_at") or "").strip() or _now_date(),
                "summary": str(item.get("summary") or "").strip()[:500],
            }
        )

    _write_index(settings, seeded_notes)


def _to_public_note(item: Dict) -> Dict:
    note_id = str(item.get("id") or "")
    return {
        "id": note_id,
        "title": str(item.get("title") or ""),
        "path": f"{CONTENT_ENDPOINT_PREFIX}/{note_id}/content",
        "tags": _normalize_tags(item.get("tags") or []),
        "updated_at": str(item.get("updated_at") or ""),
        "summary": str(item.get("summary") or ""),
    }


def list_notebook_notes(settings) -> List[Dict]:
    ensure_notebook_store(settings)
    return [_to_public_note(item) for item in _read_index(settings)]


def _load_note_item(settings, note_id: str) -> Dict:
    ensure_notebook_store(settings)
    cleaned_id = _normalize_id(note_id)
    if not cleaned_id:
        raise NotebookNotFoundError("笔记不存在")
    notes = _read_index(settings)
    for item in notes:
        if item.get("id") == cleaned_id:
            return item
    raise NotebookNotFoundError("笔记不存在")


def load_notebook_note_content(settings, note_id: str) -> str:
    item = _load_note_item(settings, note_id)
    paths = _note_paths(settings, str(item.get("id") or ""))
    if not paths.markdown_path.exists():
        raise NotebookNotFoundError("笔记内容不存在")
    return paths.markdown_path.read_text(encoding="utf-8")


def _load_chunks(paths: NotebookNotePaths) -> List[Dict]:
    if not paths.chunks_path.exists():
        return []
    items: List[Dict] = []
    with paths.chunks_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                items.append(item)
    return items


def _save_chunks(paths: NotebookNotePaths, chunks: List[Dict]) -> None:
    with paths.chunks_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def _load_embeddings(paths: NotebookNotePaths) -> Optional[Dict]:
    if not paths.embeddings_path.exists():
        return None
    try:
        return json.loads(paths.embeddings_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_embeddings(paths: NotebookNotePaths, payload: Dict) -> None:
    paths.embeddings_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_embedding_client(settings) -> EmbeddingClient:
    return EmbeddingClient(
        base_url=settings.EMBEDDING_BASE_URL,
        api_key=settings.EMBEDDING_API_KEY,
        model=settings.EMBEDDING_MODEL,
        timeout_sec=settings.EMBEDDING_TIMEOUT_SEC,
    )


def _ensure_note_artifacts(
    *,
    settings,
    note_id: str,
    markdown: str,
    strict: bool = False,
) -> Tuple[List[Dict], Dict[str, List[float]]]:
    paths = _note_paths(settings, note_id)
    paths.note_dir.mkdir(parents=True, exist_ok=True)
    chunks = _load_chunks(paths)
    if not chunks:
        strategy = {
            "mode": "section_then_split",
            "target_tokens": int(settings.ARXIV_CHUNK_TARGET_TOKENS),
            "max_tokens": int(settings.ARXIV_CHUNK_MAX_TOKENS),
            "overlap_tokens": int(settings.ARXIV_CHUNK_OVERLAP_TOKENS),
            "min_tokens": int(settings.ARXIV_CHUNK_MIN_TOKENS),
        }
        chunks = build_chunks_from_markdown(
            markdown=markdown,
            canonical_id=note_id,
            strategy=strategy,
        )
        if not chunks:
            raise NotebookServiceError("笔记切分失败，未生成可检索分块")
        _save_chunks(paths, chunks)

    chunk_ids = [str(c.get("chunk_id") or "") for c in chunks if c.get("chunk_id")]
    if not chunk_ids:
        raise NotebookServiceError("笔记分块缺少 chunk_id")

    cached = _load_embeddings(paths)
    if isinstance(cached, dict) and cached.get("model") == settings.EMBEDDING_MODEL:
        items = cached.get("items")
        if isinstance(items, list):
            embedding_map: Dict[str, List[float]] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("chunk_id") or "")
                vector = item.get("embedding")
                if cid and isinstance(vector, list) and vector:
                    embedding_map[cid] = [float(v) for v in vector]
            if all(cid in embedding_map for cid in chunk_ids):
                return chunks, embedding_map

    try:
        client = _build_embedding_client(settings)
        vectors = client.embed_texts_batched(
            [str(c.get("text") or "") for c in chunks],
            batch_size=int(settings.EMBEDDING_BATCH_SIZE),
        )
    except (EmbeddingConfigError, EmbeddingServiceError) as exc:
        if strict:
            raise NotebookServiceError(f"向量索引生成失败: {exc}") from exc
        raise

    if len(vectors) != len(chunks):
        raise NotebookServiceError("向量生成数量与 chunks 数量不一致")

    items = []
    embedding_map = {}
    for chunk, vector in zip(chunks, vectors):
        cid = str(chunk.get("chunk_id") or "")
        if not cid:
            continue
        embedding_map[cid] = vector
        items.append({"chunk_id": cid, "embedding": vector})
    if not embedding_map:
        raise NotebookServiceError("向量索引为空")
    _save_embeddings(
        paths,
        {
            "schema_version": "v1",
            "generated_at": _now_iso(),
            "provider": "siliconflow",
            "model": settings.EMBEDDING_MODEL,
            "count": len(items),
            "items": items,
        },
    )
    return chunks, embedding_map


def create_notebook_note(
    *,
    settings,
    title: str,
    summary: str,
    tags: List[str],
    content: str,
) -> Dict:
    ensure_notebook_store(settings)
    notes = _read_index(settings)
    existing_ids = {str(item.get("id") or "") for item in notes}
    normalized_title = str(title or "").strip()[:200]
    normalized_content = str(content or "").strip()
    if not normalized_title:
        raise NotebookServiceError("标题不能为空")
    if not normalized_content:
        raise NotebookServiceError("内容不能为空")

    base_id = _normalize_id(normalized_title) or "note"
    note_id = ""
    for _ in range(64):
        candidate = f"{base_id}-{int(time.time())}-{secrets.randbelow(10000):04d}"
        if candidate not in existing_ids:
            note_id = candidate
            break
    if not note_id:
        raise NotebookServiceError("无法生成笔记ID，请重试")

    note_paths = _note_paths(settings, note_id)
    note_paths.note_dir.mkdir(parents=True, exist_ok=True)
    note_paths.markdown_path.write_text(normalized_content, encoding="utf-8")

    try:
        _ensure_note_artifacts(
            settings=settings,
            note_id=note_id,
            markdown=normalized_content,
            strict=True,
        )
    except Exception:
        shutil.rmtree(note_paths.note_dir, ignore_errors=True)
        raise

    item = {
        "id": note_id,
        "title": normalized_title,
        "tags": _normalize_tags(tags),
        "updated_at": _now_date(),
        "summary": _safe_summary(summary, normalized_content),
    }
    notes.insert(0, item)
    try:
        _write_index(settings, notes)
    except Exception:
        shutil.rmtree(note_paths.note_dir, ignore_errors=True)
        raise
    return _to_public_note(item)


def _build_note_context(
    *,
    ranked_by_note: List[Dict],
    max_tokens: int,
) -> Tuple[str, List[Dict]]:
    blocks: List[str] = []
    total_tokens = 0
    source_rows: List[Dict] = []
    source_counter = 1

    for group in ranked_by_note:
        note = group["note"]
        note_id = str(note.get("id") or "")
        note_title = str(note.get("title") or "")
        note_tags = _normalize_tags(note.get("tags") or [])
        header = f"[note {note_id}] {note_title} | tags={','.join(note_tags) or '未分类'}\n"
        header_tokens = _token_count(header)
        if total_tokens + header_tokens > max_tokens:
            break
        blocks.append(header)
        total_tokens += header_tokens

        for item in group["items"]:
            chunk = item["chunk"]
            score = float(item["score"])
            source_id = f"S{source_counter}"
            source_counter += 1
            chunk_text = str(chunk.get("text") or "").strip()
            chunk_id = str(chunk.get("chunk_id") or "")
            if not chunk_text:
                continue
            block = f"[{source_id} | chunk_id={chunk_id} | score={score:.4f}]\n{chunk_text}\n"
            block_tokens = _token_count(block)
            if total_tokens + block_tokens > max_tokens:
                break
            blocks.append(block)
            total_tokens += block_tokens
            source_rows.append(
                {
                    "source_id": source_id,
                    "note_id": note_id,
                    "title": note_title,
                    "path": f"{CONTENT_ENDPOINT_PREFIX}/{note_id}/content",
                    "tags": note_tags,
                    "snippet": _build_snippet(chunk_text),
                    "score": round(score, 6),
                }
            )

        if total_tokens < max_tokens:
            blocks.append("")

    return "\n".join(blocks).strip(), source_rows


def build_notebook_retrieval_payload(
    *,
    settings,
    query: str,
) -> Dict:
    ensure_notebook_store(settings)
    notes = _read_index(settings)
    if not notes:
        raise NotebookServiceError("暂无可检索笔记")
    cleaned_query = str(query or "").strip()
    if not cleaned_query:
        raise NotebookServiceError("问题不能为空")

    try:
        embedding_client = _build_embedding_client(settings)
        query_embedding = embedding_client.embed_texts([cleaned_query])[0]
    except (EmbeddingConfigError, EmbeddingServiceError) as exc:
        raise NotebookServiceError(f"向量检索失败: {exc}") from exc

    per_note_chunks = max(1, int(getattr(settings, "NOTEBOOK_MAX_CHUNKS_PER_NOTE", 3) or 3))
    max_notes = max(1, int(getattr(settings, "NOTEBOOK_MAX_NOTES_PER_QUERY", 4) or 4))

    note_rankings: List[Dict] = []
    for note in notes:
        note_id = str(note.get("id") or "")
        if not note_id:
            continue
        paths = _note_paths(settings, note_id)
        if not paths.markdown_path.exists():
            continue
        markdown = paths.markdown_path.read_text(encoding="utf-8")
        try:
            chunks, embedding_map = _ensure_note_artifacts(
                settings=settings,
                note_id=note_id,
                markdown=markdown,
                strict=False,
            )
        except (NotebookServiceError, EmbeddingConfigError, EmbeddingServiceError) as exc:
            logger.warning("notebook-skip-note note_id=%s reason=%s", note_id, str(exc)[:180])
            continue

        ranked = rank_chunks(
            query_embedding=query_embedding,
            chunks=chunks,
            chunk_embedding_map=embedding_map,
            top_k=max(1, min(len(chunks), per_note_chunks)),
        )
        if not ranked:
            continue
        note_rankings.append(
            {
                "note": note,
                "max_score": float(ranked[0]["score"]),
                "items": ranked[:per_note_chunks],
            }
        )

    if not note_rankings:
        return {
            "query": cleaned_query,
            "context_text": "",
            "sources": [],
        }

    note_rankings.sort(key=lambda x: x["max_score"], reverse=True)
    selected_rankings = note_rankings[:max_notes]
    context_text, sources = _build_note_context(
        ranked_by_note=selected_rankings,
        max_tokens=max(500, int(getattr(settings, "NOTEBOOK_CONTEXT_MAX_TOKENS", 3200) or 3200)),
    )

    return {
        "query": cleaned_query,
        "context_text": context_text,
        "sources": sources,
    }
