"""arXiv paper parse + retrieval pipeline.

Review note:
- 支持多篇论文联合检索：会话 active papers 可同时参与召回与重排。
- 构建上下文时保留来源信息（pdf 文件名 + 标题 + chunk_id + score），便于审阅与追踪。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple
import logging
import json
import time

from app.services.cache.paper_store import (
    build_paper_paths,
    ensure_paper_dir,
    has_ready_parsed_artifacts,
    load_chunk_embeddings,
    load_chunks_jsonl,
    load_meta,
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
    extract_arxiv_targets,
    remove_detected_arxiv_references,
)
from app.services.sources.arxiv.source_to_markdown import parse_arxiv_source_to_markdown
from app.services.sources.arxiv.tei_to_markdown import tei_to_markdown

logger = logging.getLogger("uvicorn.error")
ProgressCallback = Optional[Callable[[Dict], None]]


class ArxivPipelineError(RuntimeError):
    """Raised when arXiv pipeline execution fails."""


@dataclass
class ArxivContextPayload:
    """Context payload to inject before model generation."""

    targets: List[ArxivTarget]
    papers: List[Dict]
    query_text: str
    context_text: str
    context_prompt: str
    retrieval_meta: Dict


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_progress(
    progress_callback: ProgressCallback,
    *,
    key: str,
    status: str,
    message: str,
    paper_id: str = "",
    filename: str = "",
    elapsed_ms: Optional[int] = None,
    cached: Optional[bool] = None,
) -> None:
    if progress_callback is None:
        return
    payload = {
        "step_id": f"{paper_id or 'global'}:{key}",
        "key": key,
        "status": status,
        "message": message,
    }
    if paper_id:
        payload["paper_id"] = paper_id
    if filename:
        payload["filename"] = filename
    if elapsed_ms is not None:
        payload["elapsed_ms"] = int(elapsed_ms)
    if cached is not None:
        payload["cached"] = bool(cached)
    try:
        progress_callback(payload)
    except Exception:
        # 进度回调只影响可视化，不应中断主流程。
        return


def _default_query() -> str:
    return "请基于论文给出简要摘要，并回答用户的核心问题。"


def _build_context_prompt(papers: List[Dict], context_text: str) -> str:
    paper_lines = []
    for paper in papers:
        filename = paper.get("filename") or f"{paper.get('canonical_id', '')}.pdf"
        title = (paper.get("title") or "").strip()
        if title:
            paper_lines.append(f"- {filename} | {title} | arxiv:{paper.get('paper_id')}")
        else:
            paper_lines.append(f"- {filename} | arxiv:{paper.get('paper_id')}")

    paper_section = "\n".join(paper_lines).strip() or "- 无"
    return (
        "你将获得来自一组 arXiv 论文的检索片段。"
        "请优先基于这些片段回答用户问题；当片段不足时明确说明不确定。\n\n"
        f"[papers]\n{paper_section}\n\n"
        f"{context_text}"
    )


def _build_embedding_client(settings) -> EmbeddingClient:
    return EmbeddingClient(
        base_url=settings.EMBEDDING_BASE_URL,
        api_key=settings.EMBEDDING_API_KEY,
        model=settings.EMBEDDING_MODEL,
        timeout_sec=settings.EMBEDDING_TIMEOUT_SEC,
    )


def _ensure_chunk_embedding_map(
    paths,
    chunks,
    settings,
    client: EmbeddingClient,
    *,
    paper_id: str,
    filename: str,
    progress_callback: ProgressCallback = None,
) -> Dict[str, List[float]]:
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
                _emit_progress(
                    progress_callback,
                    key="embed_chunks",
                    status="done",
                    message=f"复用向量缓存：{filename}",
                    paper_id=paper_id,
                    filename=filename,
                    elapsed_ms=0,
                    cached=True,
                )
                return embedding_map

    started = time.perf_counter()
    _emit_progress(
        progress_callback,
        key="embed_chunks",
        status="running",
        message=f"正在生成向量索引：{filename}",
        paper_id=paper_id,
        filename=filename,
    )
    texts = [c.get("text", "") for c in chunks]
    vectors = client.embed_texts_batched(texts, batch_size=settings.EMBEDDING_BATCH_SIZE)
    if len(vectors) != len(chunks):
        raise ArxivPipelineError(
            f"Chunk embedding 数量不匹配: expected={len(chunks)}, got={len(vectors)}"
        )

    items = []
    embedding_map: Dict[str, List[float]] = {}
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
    _emit_progress(
        progress_callback,
        key="embed_chunks",
        status="done",
        message=f"向量索引完成：{filename}",
        paper_id=paper_id,
        filename=filename,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    return embedding_map


def _prepare_parsed_files(
    target: ArxivTarget,
    settings,
    paths,
    progress_callback: ProgressCallback = None,
) -> None:
    ensure_paper_dir(paths)
    downloaded_url = None
    pdf_size = None
    pdf_sha256 = None
    filename = f"{target.safe_id}.pdf"

    if not paths.pdf_path.exists():
        started = time.perf_counter()
        _emit_progress(
            progress_callback,
            key="download_pdf",
            status="running",
            message=f"正在下载论文 PDF：{filename}",
            paper_id=target.paper_id,
            filename=filename,
        )
        downloaded_url, pdf_size, pdf_sha256 = download_arxiv_pdf(
            paper_id=target.paper_id,
            canonical_id=target.canonical_id,
            output_pdf=paths.pdf_path,
            timeout_sec=settings.ARXIV_DOWNLOAD_TIMEOUT_SEC,
        )
        _emit_progress(
            progress_callback,
            key="download_pdf",
            status="done",
            message=f"PDF 下载完成：{filename}",
            paper_id=target.paper_id,
            filename=filename,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    else:
        _emit_progress(
            progress_callback,
            key="download_pdf",
            status="done",
            message=f"复用本地 PDF：{filename}",
            paper_id=target.paper_id,
            filename=filename,
            elapsed_ms=0,
            cached=True,
        )

    parsed = None
    parse_engine = "source_latex"
    parse_meta: Dict[str, object] = {}
    source_fallback_reason = ""

    started = time.perf_counter()
    _emit_progress(
        progress_callback,
        key="parse_source",
        status="running",
        message=f"正在解析 LaTeX 源码：{filename}",
        paper_id=target.paper_id,
        filename=filename,
    )
    try:
        parsed, source_meta = parse_arxiv_source_to_markdown(
            paper_id=target.paper_id,
            canonical_id=target.canonical_id,
            paper_dir=paths.paper_dir,
            markdown_path=paths.markdown_path,
            timeout_sec=settings.ARXIV_DOWNLOAD_TIMEOUT_SEC,
        )
        parse_meta["latex_source"] = source_meta
        _emit_progress(
            progress_callback,
            key="parse_source",
            status="done",
            message=f"LaTeX 源码解析完成：{filename}",
            paper_id=target.paper_id,
            filename=filename,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        parse_engine = "grobid"
        source_fallback_reason = str(exc)
        _emit_progress(
            progress_callback,
            key="parse_source",
            status="error",
            message=f"LaTeX 源码解析失败，回退 GROBID：{filename}",
            paper_id=target.paper_id,
            filename=filename,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    if parsed is None:
        if not paths.tei_path.exists():
            started = time.perf_counter()
            _emit_progress(
                progress_callback,
                key="parse_pdf",
                status="running",
                message=f"正在解析 PDF（GROBID）：{filename}",
                paper_id=target.paper_id,
                filename=filename,
            )
            parse_pdf_to_tei(
                pdf_path=paths.pdf_path,
                tei_path=paths.tei_path,
                service_url=settings.GROBID_URL,
                timeout_sec=settings.GROBID_TIMEOUT_SEC,
            )
            _emit_progress(
                progress_callback,
                key="parse_pdf",
                status="done",
                message=f"PDF 解析完成：{filename}",
                paper_id=target.paper_id,
                filename=filename,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        else:
            _emit_progress(
                progress_callback,
                key="parse_pdf",
                status="done",
                message=f"复用解析结果（TEI）：{filename}",
                paper_id=target.paper_id,
                filename=filename,
                elapsed_ms=0,
                cached=True,
            )
        parsed = tei_to_markdown(paths.tei_path, paths.markdown_path)
        parse_meta["grobid"] = {
            "service_url": settings.GROBID_URL,
            "parsed_at": _now_iso(),
            "tei_path": str(paths.tei_path),
        }

    started = time.perf_counter()
    _emit_progress(
        progress_callback,
        key="chunk_paper",
        status="running",
        message=f"正在切分章节与段落：{filename}",
        paper_id=target.paper_id,
        filename=filename,
    )
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
    _emit_progress(
        progress_callback,
        key="chunk_paper",
        status="done",
        message=f"切分完成：{filename}",
        paper_id=target.paper_id,
        filename=filename,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )

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
        "parse": {
            "engine": parse_engine,
            "updated_at": _now_iso(),
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
    if source_fallback_reason:
        meta["parse"]["source_fallback_reason"] = source_fallback_reason
    if parse_meta.get("latex_source"):
        meta["latex_source"] = parse_meta["latex_source"]
    if parse_meta.get("grobid"):
        meta["grobid"] = parse_meta["grobid"]
    save_meta(paths, meta)


def _read_paper_title(paths) -> str:
    if not paths.markdown_path.exists():
        return ""
    try:
        with paths.markdown_path.open("r", encoding="utf-8") as f:
            for _ in range(24):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[2:].strip()
    except Exception:
        return ""
    return ""


def _build_paper_descriptor(target: ArxivTarget, paths) -> Dict:
    meta = load_meta(paths) or {}
    title = _read_paper_title(paths)
    safe_id = target.safe_id
    filename = f"{safe_id}.pdf"
    return {
        "paper_id": target.paper_id,
        "canonical_id": target.canonical_id,
        "safe_id": safe_id,
        "filename": filename,
        "pdf_url": f"/papers/{safe_id}/{filename}",
        "title": title,
        "meta_updated_at": meta.get("updated_at"),
    }


def _prepare_and_load_chunks_for_target(
    target: ArxivTarget,
    settings,
    progress_callback: ProgressCallback = None,
) -> Tuple[List[Dict], Dict, object]:
    paths = build_paper_paths(settings.PAPER_DATA_DIR, target.safe_id)
    try:
        if not has_ready_parsed_artifacts(paths):
            _prepare_parsed_files(
                target=target,
                settings=settings,
                paths=paths,
                progress_callback=progress_callback,
            )
    except Exception as exc:
        raise ArxivPipelineError(f"论文解析失败: {exc}") from exc

    chunks = load_chunks_jsonl(paths)
    if not chunks:
        raise ArxivPipelineError("论文已解析但未生成有效 chunks。")
    descriptor = _build_paper_descriptor(target, paths)
    return chunks, descriptor, paths


def _build_ranked_chunks_for_paper(
    *,
    target: ArxivTarget,
    paper_chunks: List[Dict],
    paper_desc: Dict,
    paths,
    settings,
    embedding_client: EmbeddingClient,
    query_embedding: List[float],
    progress_callback: ProgressCallback = None,
) -> Tuple[List[Dict], Dict]:
    filename = paper_desc.get("filename") or f"{target.safe_id}.pdf"
    chunk_embedding_map = _ensure_chunk_embedding_map(
        paths=paths,
        chunks=paper_chunks,
        settings=settings,
        client=embedding_client,
        paper_id=target.paper_id,
        filename=filename,
        progress_callback=progress_callback,
    )
    started = time.perf_counter()
    _emit_progress(
        progress_callback,
        key="retrieve_chunks",
        status="running",
        message=f"正在检索相关片段：{filename}",
        paper_id=target.paper_id,
        filename=filename,
    )
    ranked_all = rank_chunks(
        query_embedding=query_embedding,
        chunks=paper_chunks,
        chunk_embedding_map=chunk_embedding_map,
        top_k=len(paper_chunks),
    )
    if not ranked_all:
        _emit_progress(
            progress_callback,
            key="retrieve_chunks",
            status="done",
            message=f"检索完成（无命中）：{filename}",
            paper_id=target.paper_id,
            filename=filename,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return [], {
            "paper_id": target.paper_id,
            "canonical_id": target.canonical_id,
            "max_score": 0.0,
            "low_score_mode": True,
            "topk": [],
        }

    max_score = float(ranked_all[0]["score"])
    low_score_mode = max_score < float(settings.ARXIV_LOW_SCORE_FULLTEXT_THRESHOLD)
    ranked_used = ranked_all if low_score_mode else ranked_all[: settings.ARXIV_CONTEXT_TOP_K]

    decorated = []
    for item in ranked_used:
        chunk = dict(item["chunk"])
        chunk["paper_id"] = paper_desc["paper_id"]
        chunk["paper_canonical_id"] = paper_desc["canonical_id"]
        chunk["paper_filename"] = paper_desc["filename"]
        chunk["paper_title"] = paper_desc.get("title") or ""
        decorated.append({"chunk": chunk, "score": float(item["score"])})

    topk = [
        {
            "rank": i + 1,
            "chunk_id": item["chunk"].get("chunk_id"),
            "score": round(float(item["score"]), 6),
        }
        for i, item in enumerate(ranked_all[: settings.ARXIV_CONTEXT_TOP_K])
    ]
    debug = {
        "paper_id": target.paper_id,
        "canonical_id": target.canonical_id,
        "max_score": max_score,
        "low_score_mode": low_score_mode,
        "topk": topk,
    }
    _emit_progress(
        progress_callback,
        key="retrieve_chunks",
        status="done",
        message=f"检索完成：{filename}",
        paper_id=target.paper_id,
        filename=filename,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    return decorated, debug


def build_arxiv_context_for_targets(
    message: str,
    targets: List[ArxivTarget],
    settings,
    progress_callback: ProgressCallback = None,
) -> Optional[ArxivContextPayload]:
    """
    Build merged retrieval context from one or many arXiv targets.
    """
    if not targets:
        return None

    unique_map: Dict[str, ArxivTarget] = {}
    for target in targets:
        unique_map[target.canonical_id] = target
    unique_targets = list(unique_map.values())
    _emit_progress(
        progress_callback,
        key="arxiv_detected",
        status="done",
        message=f"识别到 arXiv 论文 {len(unique_targets)} 篇",
    )

    query_text = remove_detected_arxiv_references(message, unique_targets).strip() or _default_query()
    logger.info(
        "arxiv-query-normalized papers=%s query=%s",
        ",".join(t.paper_id for t in unique_targets),
        query_text[:180],
    )

    try:
        embedding_client = _build_embedding_client(settings)
        query_embedding = embedding_client.embed_texts([query_text])[0]
    except (EmbeddingConfigError, EmbeddingServiceError) as exc:
        raise ArxivPipelineError(f"Embedding 检索失败: {exc}") from exc

    merged_ranked: List[Dict] = []
    paper_debug: List[Dict] = []
    papers: List[Dict] = []

    for target in unique_targets:
        logger.info(
            "arxiv-detected paper_id=%s canonical_id=%s position=%s",
            target.paper_id,
            target.canonical_id,
            target.position,
        )
        chunks, paper_desc, paths = _prepare_and_load_chunks_for_target(
            target,
            settings,
            progress_callback=progress_callback,
        )
        if progress_callback:
            _emit_progress(
                progress_callback,
                key="paper_ready",
                status="done",
                message=f"论文资源就绪：{paper_desc.get('filename')}",
                paper_id=target.paper_id,
                filename=paper_desc.get("filename") or "",
            )
        papers.append(paper_desc)
        ranked_items, ranked_debug = _build_ranked_chunks_for_paper(
            target=target,
            paper_chunks=chunks,
            paper_desc=paper_desc,
            paths=paths,
            settings=settings,
            embedding_client=embedding_client,
            query_embedding=query_embedding,
            progress_callback=progress_callback,
        )
        merged_ranked.extend(ranked_items)
        paper_debug.append(ranked_debug)
        logger.info(
            "arxiv-retrieval-topk paper_id=%s max_score=%.6f threshold=%.2f low_score_mode=%s topk=%s",
            target.paper_id,
            float(ranked_debug.get("max_score", 0.0)),
            float(settings.ARXIV_LOW_SCORE_FULLTEXT_THRESHOLD),
            bool(ranked_debug.get("low_score_mode", False)),
            json.dumps(ranked_debug.get("topk", []), ensure_ascii=False),
        )

    if not merged_ranked:
        raise ArxivPipelineError("论文向量检索结果为空。")

    merged_ranked.sort(key=lambda x: float(x["score"]), reverse=True)

    context_text = build_context_text(
        ranked_items=merged_ranked,
        max_chunks=None,
        max_tokens=settings.ARXIV_CONTEXT_MAX_TOKENS,
    )
    if not context_text:
        raise ArxivPipelineError("论文检索结果为空。")

    logger.info(
        "arxiv-context-ready papers=%d ranked_total=%d context_chars=%d",
        len(papers),
        len(merged_ranked),
        len(context_text),
    )
    _emit_progress(
        progress_callback,
        key="retrieval_ready",
        status="done",
        message=f"检索完成，准备生成回答（{len(papers)} 篇）",
    )

    retrieval_items = [
        {
            "rank": i + 1,
            "paper_id": item["chunk"].get("paper_id"),
            "canonical_id": item["chunk"].get("paper_canonical_id"),
            "chunk_id": item["chunk"].get("chunk_id"),
            "score": round(float(item["score"]), 6),
            "filename": item["chunk"].get("paper_filename"),
            "title": item["chunk"].get("paper_title"),
        }
        for i, item in enumerate(merged_ranked[: max(8, settings.ARXIV_CONTEXT_TOP_K)])
    ]

    return ArxivContextPayload(
        targets=unique_targets,
        papers=papers,
        query_text=query_text,
        context_text=context_text,
        context_prompt=_build_context_prompt(papers, context_text),
        retrieval_meta={
            "query": query_text,
            "paper_count": len(papers),
            "papers": papers,
            "per_paper": paper_debug,
            "items": retrieval_items,
            "context_max_tokens": int(settings.ARXIV_CONTEXT_MAX_TOKENS),
        },
    )


def build_arxiv_context_for_message(message: str, settings) -> Optional[ArxivContextPayload]:
    """
    Parse arXiv targets from message and build merged retrieval context.
    """
    targets = extract_arxiv_targets(message)
    if not targets:
        return None
    return build_arxiv_context_for_targets(message=message, targets=targets, settings=settings)
