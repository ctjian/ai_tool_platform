"""arXiv paper parse + retrieval pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import logging
import json

from app.services.cache.paper_store import (
    build_paper_paths,
    ensure_paper_dir,
    has_ready_parsed_artifacts,
    load_chunk_embeddings,
    load_chunks_jsonl,
    save_chunk_embeddings,
    save_chunks_jsonl,
    save_meta,
)
from app.services.retrieval.chunker import build_chunks_from_markdown
from app.services.retrieval.context_builder import build_context_text
from app.services.retrieval.embedding_client import (
    EmbeddingClient,
    EmbeddingConfigError,
    EmbeddingServiceError,
)
from app.services.retrieval.ranker import rank_chunks
from app.services.sources.arxiv.downloader import download_arxiv_pdf
from app.services.sources.arxiv.grobid_client import parse_pdf_to_tei
from app.services.sources.arxiv.id_parser import (
    ArxivTarget,
    extract_single_arxiv_target,
    remove_detected_arxiv_reference,
)
from app.services.sources.arxiv.tei_to_markdown import tei_to_markdown

logger = logging.getLogger("uvicorn.error")


class ArxivPipelineError(RuntimeError):
    """Raised when arXiv pipeline execution fails."""


@dataclass
class ArxivContextPayload:
    """Context payload to inject before model generation."""

    target: ArxivTarget
    query_text: str
    context_text: str
    context_prompt: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_query() -> str:
    return "请基于论文给出简要摘要，并回答用户的核心问题。"


def _build_context_prompt(target: ArxivTarget, context_text: str) -> str:
    return (
        "你将获得来自一篇 arXiv 论文的检索片段。"
        "请优先基于这些片段回答用户问题；当片段不足时明确说明不确定。\n\n"
        f"[paper_id] arxiv:{target.paper_id}\n"
        f"[canonical_id] {target.canonical_id}\n\n"
        f"{context_text}"
    )


def _build_embedding_client(settings) -> EmbeddingClient:
    return EmbeddingClient(
        base_url=settings.EMBEDDING_BASE_URL,
        api_key=settings.EMBEDDING_API_KEY,
        model=settings.EMBEDDING_MODEL,
        timeout_sec=settings.EMBEDDING_TIMEOUT_SEC,
    )


def _ensure_chunk_embedding_map(paths, chunks, settings, client: EmbeddingClient) -> dict[str, list[float]]:
    chunk_ids = [c.get("chunk_id") for c in chunks if c.get("chunk_id")]
    if not chunk_ids:
        raise ArxivPipelineError("chunks 缺少 chunk_id，无法执行向量检索。")

    cached = load_chunk_embeddings(paths)
    if isinstance(cached, dict) and cached.get("model") == settings.EMBEDDING_MODEL:
        cached_items = cached.get("items", [])
        if isinstance(cached_items, list):
            embedding_map = {}
            for item in cached_items:
                if not isinstance(item, dict):
                    continue
                chunk_id = item.get("chunk_id")
                vector = item.get("embedding")
                if chunk_id and isinstance(vector, list) and vector:
                    embedding_map[chunk_id] = [float(v) for v in vector]
            if all(chunk_id in embedding_map for chunk_id in chunk_ids):
                return embedding_map

    texts = [c.get("text", "") for c in chunks]
    vectors = client.embed_texts_batched(texts, batch_size=settings.EMBEDDING_BATCH_SIZE)
    if len(vectors) != len(chunks):
        raise ArxivPipelineError(
            f"Chunk embedding 数量不匹配: expected={len(chunks)}, got={len(vectors)}"
        )

    items = []
    embedding_map: dict[str, list[float]] = {}
    for chunk, vector in zip(chunks, vectors):
        chunk_id = chunk.get("chunk_id")
        if not chunk_id:
            continue
        embedding_map[chunk_id] = vector
        items.append({"chunk_id": chunk_id, "embedding": vector})

    save_chunk_embeddings(
        paths,
        {
            "schema_version": "v1",
            "provider": "siliconflow",
            "model": settings.EMBEDDING_MODEL,
            "generated_at": _now_iso(),
            "count": len(items),
            "items": items,
        },
    )
    logger.info(
        "arxiv-embeddings-ready model=%s paper_dir=%s count=%d",
        settings.EMBEDDING_MODEL,
        paths.paper_dir,
        len(items),
    )
    return embedding_map


def _prepare_parsed_files(target: ArxivTarget, settings, paths) -> None:
    ensure_paper_dir(paths)
    downloaded_url = None
    pdf_size = None
    pdf_sha256 = None

    if not paths.pdf_path.exists():
        downloaded_url, pdf_size, pdf_sha256 = download_arxiv_pdf(
            paper_id=target.paper_id,
            canonical_id=target.canonical_id,
            output_pdf=paths.pdf_path,
            timeout_sec=settings.ARXIV_DOWNLOAD_TIMEOUT_SEC,
        )

    if not paths.tei_path.exists():
        parse_pdf_to_tei(
            pdf_path=paths.pdf_path,
            tei_path=paths.tei_path,
            service_url=settings.GROBID_URL,
            timeout_sec=settings.GROBID_TIMEOUT_SEC,
        )

    parsed = tei_to_markdown(paths.tei_path, paths.markdown_path)
    strategy = {
        "mode": "section_then_split",
        "target_tokens": settings.ARXIV_CHUNK_TARGET_TOKENS,
        "max_tokens": settings.ARXIV_CHUNK_MAX_TOKENS,
        "overlap_tokens": settings.ARXIV_CHUNK_OVERLAP_TOKENS,
        "min_tokens": settings.ARXIV_CHUNK_MIN_TOKENS,
    }
    chunks = build_chunks_from_markdown(
        markdown=parsed.markdown,
        canonical_id=target.canonical_id,
        strategy=strategy,
    )
    save_chunks_jsonl(paths, chunks)

    pdf_stat = paths.pdf_path.stat()
    meta = {
        "schema_version": "v1",
        "paper_id": f"arxiv:{target.paper_id}",
        "canonical_id": target.canonical_id,
        "safe_id": target.safe_id,
        "source": {
            "type": "arxiv",
            "input_fragment": target.source_fragment,
            "paper_url": f"https://arxiv.org/abs/{target.paper_id}",
            "position": target.position,
        },
        "pdf": {
            "path": str(paths.pdf_path),
            "size_bytes": pdf_size or pdf_stat.st_size,
            "sha256": pdf_sha256 or "",
            "downloaded_url": downloaded_url or "",
        },
        "grobid": {
            "service_url": settings.GROBID_URL,
            "parsed_at": _now_iso(),
            "tei_path": str(paths.tei_path),
        },
        "markdown": {
            "path": str(paths.markdown_path),
            "char_count": len(parsed.markdown),
        },
        "sections": [
            {
                "section_id": sec.section_id,
                "level": sec.level,
                "title": sec.title,
                "order": sec.order,
                "page_start": sec.page_start,
                "page_end": sec.page_end,
                "char_start": sec.char_start,
                "char_end": sec.char_end,
            }
            for sec in parsed.sections
        ],
        "chunks": {
            "path": str(paths.chunks_path),
            "count": len(chunks),
            "strategy": strategy,
        },
        "status": "ready",
        "updated_at": _now_iso(),
    }
    save_meta(paths, meta)


def build_arxiv_context_for_message(message: str, settings) -> Optional[ArxivContextPayload]:
    """
    Parse arXiv at message head/tail, prepare cached chunks, then build retrieval context.
    """
    target = extract_single_arxiv_target(message, window_chars=settings.ARXIV_WINDOW_CHARS)
    if not target:
        return None
    logger.info(
        "arxiv-detected paper_id=%s canonical_id=%s position=%s",
        target.paper_id,
        target.canonical_id,
        target.position,
    )

    paths = build_paper_paths(settings.PAPER_DATA_DIR, target.safe_id)
    try:
        if not has_ready_parsed_artifacts(paths):
            _prepare_parsed_files(target=target, settings=settings, paths=paths)
    except Exception as exc:
        raise ArxivPipelineError(f"论文解析失败: {exc}") from exc

    chunks = load_chunks_jsonl(paths)
    if not chunks:
        raise ArxivPipelineError("论文已解析但未生成有效 chunks。")

    query_text = remove_detected_arxiv_reference(message, target).strip() or _default_query()
    logger.info("arxiv-query-normalized paper_id=%s query=%s", target.paper_id, query_text[:180])
    try:
        embedding_client = _build_embedding_client(settings)
        chunk_embedding_map = _ensure_chunk_embedding_map(
            paths=paths,
            chunks=chunks,
            settings=settings,
            client=embedding_client,
        )
        query_embedding = embedding_client.embed_texts([query_text])[0]
    except (EmbeddingConfigError, EmbeddingServiceError) as exc:
        raise ArxivPipelineError(f"Embedding 检索失败: {exc}") from exc

    ranked = rank_chunks(
        query_embedding=query_embedding,
        chunks=chunks,
        chunk_embedding_map=chunk_embedding_map,
        top_k=settings.ARXIV_CONTEXT_TOP_K,
    )
    if not ranked:
        raise ArxivPipelineError("论文向量检索结果为空。")
    topk_scores = [
        {
            "rank": i + 1,
            "chunk_id": item["chunk"].get("chunk_id"),
            "score": round(float(item["score"]), 6),
        }
        for i, item in enumerate(ranked)
    ]
    logger.info(
        "arxiv-retrieval-topk paper_id=%s topk=%s",
        target.paper_id,
        json.dumps(topk_scores, ensure_ascii=False),
    )

    context_text = build_context_text(
        ranked_items=ranked,
        max_chunks=settings.ARXIV_CONTEXT_TOP_K,
        max_chars=settings.ARXIV_CONTEXT_MAX_CHARS,
    )
    if not context_text:
        raise ArxivPipelineError("论文检索结果为空。")
    logger.info(
        "arxiv-context-ready paper_id=%s chunks_total=%d ranked=%d context_chars=%d",
        target.paper_id,
        len(chunks),
        len(ranked),
        len(context_text),
    )

    return ArxivContextPayload(
        target=target,
        query_text=query_text,
        context_text=context_text,
        context_prompt=_build_context_prompt(target, context_text),
    )
