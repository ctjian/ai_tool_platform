"""Arxiv LaTeX translation job service.

Review note:
- 提供异步任务式翻译服务：下载源码 -> 翻译 tex -> 编译 PDF -> 产物导出。
- Job 状态保存在内存并落盘 job.json，前端可轮询获取实时进度。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import asyncio
import json
import re
import shutil
import traceback
import uuid

from app.config import settings
from app.custom_tools.arxiv_translate.compiler import (
    build_project_zip,
    command_exists,
    compile_latex_project,
    copy_file,
    ensure_ctex_support,
)
from app.custom_tools.arxiv_translate.defaults import (
    DEFAULT_CHUNK_MAX_TOKENS,
    DEFAULT_COMPILE_REPAIR_BASE_WINDOW,
    DEFAULT_COMPILE_TIMEOUT_SEC,
    DEFAULT_CONCURRENCY,
    DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    DEFAULT_LLM_TIMEOUT_SEC,
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_COMPILE_TRIES,
    DEFAULT_TARGET_LANGUAGE,
    DEFAULT_TRANSLATE_MODEL,
)
from app.custom_tools.arxiv_translate.downloader import (
    download_arxiv_source_archive,
    extract_source_archive,
    resolve_arxiv_input,
)
from app.custom_tools.arxiv_translate.splitter import (
    LatexSegment,
    build_translation_segments,
    ensure_section_title_bold,
    guard_translated_segment,
    strip_latex_comments,
)
from app.custom_tools.arxiv_translate.storage import (
    JobPaths,
    artifact_payload,
    build_job_paths,
    ensure_job_dirs,
    save_job_json,
)
from app.custom_tools.arxiv_translate.tex_project import (
    discover_tex_files,
    find_main_tex_file,
    normalize_project_root,
)
from app.custom_tools.arxiv_translate.translator import TranslatorConfig, translate_chunks
from app.services.sources.arxiv.downloader import download_arxiv_pdf


STATIC_PREFIX = "/custom-tools-files/arxiv_translate"
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_job(job_id: str) -> Dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        raise KeyError("job not found")
    return job


def _snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "input_text": job["input_text"],
        "paper_id": job.get("paper_id"),
        "canonical_id": job.get("canonical_id"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "error": job.get("error"),
        "steps": list(job.get("steps", [])),
        "artifacts": list(job.get("artifacts", [])),
        "meta": dict(job.get("meta", {})),
    }


def _append_step(
    job: Dict[str, Any],
    *,
    key: str,
    status: str,
    message: str,
    elapsed_ms: Optional[int] = None,
) -> None:
    step = {
        "step_id": f"s{len(job['steps']) + 1}",
        "key": key,
        "status": status,
        "message": message,
        "at": _now_iso(),
    }
    if elapsed_ms is not None:
        step["elapsed_ms"] = int(elapsed_ms)
    job["steps"].append(step)
    job["updated_at"] = _now_iso()


def _persist_job(job: Dict[str, Any]) -> None:
    paths: Optional[JobPaths] = job.get("_paths")
    if not paths:
        return
    payload = _snapshot(job)
    save_job_json(paths, payload)


def _read_json_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _scan_brace_payload(text: str, open_pos: int) -> Optional[str]:
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "{":
        return None
    depth = 0
    for i in range(open_pos, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_pos + 1 : i]
    return None


def _extract_command_payload(text: str, command: str) -> Optional[str]:
    pattern = re.compile(rf"\\{re.escape(command)}\*?(?:\s*\[[^\]]*\])*\s*\{{", re.DOTALL)
    m = pattern.search(text)
    if not m:
        return None
    open_pos = m.end() - 1
    return _scan_brace_payload(text, open_pos)


def _clean_tex_title(raw: str) -> str:
    out = (raw or "").strip()
    if not out:
        return ""
    out = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", out)
    out = re.sub(r"\\[a-zA-Z]+\*?", " ", out)
    out = out.replace("{", " ").replace("}", " ").replace("~", " ")
    out = re.sub(r"\s+", " ", out).strip()
    return out[:240]


def _extract_paper_title_from_main_tex(project_root: Path, main_tex_rel: Path) -> str:
    full = project_root / main_tex_rel
    if not full.exists():
        return ""
    text = full.read_text(encoding="utf-8", errors="ignore")
    for cmd in ["title", "icmltitle", "iclrtitle", "neuripsfinalcopytitle"]:
        payload = _extract_command_payload(text, cmd)
        cleaned = _clean_tex_title(payload or "")
        if cleaned:
            return cleaned
    return ""


def _build_task_name(paper_id: str, title: str) -> str:
    if title:
        return f"arXiv:{paper_id} · {title}"
    return f"arXiv:{paper_id}"


def _build_output_artifacts(paths: JobPaths) -> List[Dict[str, Any]]:
    ordered = [
        paths.output_dir / "translate_zh.pdf",
        paths.output_dir / "project.zip",
        paths.output_dir / "compile.log",
    ]
    artifacts: List[Dict[str, Any]] = []
    for file_path in ordered:
        if file_path.exists():
            artifacts.append(artifact_payload(file_path=file_path, paths=paths, static_prefix=STATIC_PREFIX))
    return artifacts


def _find_artifact_url(artifacts: List[Dict[str, Any]], name: str) -> str:
    for art in artifacts:
        if str(art.get("name") or "") == name:
            return str(art.get("url") or "")
    return ""


def _original_pdf_external_url(paper_id: str) -> str:
    pid = (paper_id or "").strip()
    if not pid:
        return ""
    return f"https://arxiv.org/pdf/{pid}.pdf"


def _ensure_original_pdf(paths: JobPaths, *, paper_id: str, canonical_id: str) -> Optional[Dict[str, Any]]:
    output_pdf = paths.output_dir / "original.pdf"
    if output_pdf.exists() and output_pdf.stat().st_size > 0:
        return artifact_payload(file_path=output_pdf, paths=paths, static_prefix=STATIC_PREFIX)
    try:
        download_arxiv_pdf(
            paper_id=paper_id,
            canonical_id=canonical_id,
            output_pdf=output_pdf,
            timeout_sec=DEFAULT_DOWNLOAD_TIMEOUT_SEC,
        )
        if output_pdf.exists() and output_pdf.stat().st_size > 0:
            return artifact_payload(file_path=output_pdf, paths=paths, static_prefix=STATIC_PREFIX)
    except Exception:
        return None
    return None


def _load_disk_job_snapshot(job_json_path: Path) -> Optional[Dict[str, Any]]:
    payload = _read_json_file(job_json_path)
    if not payload:
        return None

    required = ["job_id", "status", "input_text", "created_at", "updated_at"]
    if any(k not in payload for k in required):
        return None
    payload.setdefault("steps", [])
    payload.setdefault("artifacts", [])
    payload.setdefault("meta", {})
    return payload


def _job_paths_from_job_json(job_json_path: Path) -> Optional[JobPaths]:
    # .../<canonical_id>/<job_id>/job.json
    try:
        job_root = job_json_path.parent
        canonical_id = job_root.parent.name
        job_id = job_root.name
        return build_job_paths(settings.ARXIV_TRANSLATE_DATA_DIR, canonical_id, job_id)
    except Exception:
        return None


def _find_cached_success_snapshot(canonical_id: str) -> Optional[Dict[str, Any]]:
    base_dir = Path(settings.ARXIV_TRANSLATE_DATA_DIR) / canonical_id
    if not base_dir.exists():
        return None

    candidates = sorted(
        base_dir.glob("*/job.json"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    for job_json in candidates:
        snapshot = _load_disk_job_snapshot(job_json)
        if not snapshot or snapshot.get("status") != "succeeded":
            continue
        paths = _job_paths_from_job_json(job_json)
        if not paths:
            continue
        artifacts = _build_output_artifacts(paths) or list(snapshot.get("artifacts") or [])
        if not artifacts:
            continue
        snapshot["artifacts"] = artifacts
        meta = dict(snapshot.get("meta") or {})
        meta["cache_hit"] = True
        paper_id = str(snapshot.get("paper_id") or canonical_id)
        canonical = str(snapshot.get("canonical_id") or canonical_id)
        original_art = _ensure_original_pdf(paths, paper_id=paper_id, canonical_id=canonical)
        if original_art:
            meta["original_pdf_url"] = str(original_art.get("url") or "")
        else:
            meta.setdefault("original_pdf_url", _original_pdf_external_url(paper_id))
        title = str(meta.get("paper_title") or "")
        meta.setdefault("task_name", _build_task_name(paper_id, title))
        snapshot["meta"] = meta
        return snapshot
    return None


def _load_job_snapshot_from_disk(job_id: str) -> Optional[Dict[str, Any]]:
    base_dir = Path(settings.ARXIV_TRANSLATE_DATA_DIR)
    if not base_dir.exists():
        return None
    for job_json in base_dir.glob(f"*/*/job.json"):
        snap = _load_disk_job_snapshot(job_json)
        if not snap:
            continue
        if str(snap.get("job_id")) != job_id:
            continue
        paths = _job_paths_from_job_json(job_json)
        if paths:
            snap["artifacts"] = _build_output_artifacts(paths) or list(snap.get("artifacts") or [])
            meta = dict(snap.get("meta") or {})
            paper_id = str(snap.get("paper_id") or paths.job_root.parent.name)
            title = str(meta.get("paper_title") or "")
            meta.setdefault("task_name", _build_task_name(paper_id, title))
            snap["meta"] = meta
        return snap
    return None


def _resolve_client_config(payload: Dict[str, Any]) -> TranslatorConfig:
    api_key = (payload.get("api_key") or "").strip() or settings.OPENAI_API_KEY
    base_url = (payload.get("base_url") or "").strip() or settings.OPENAI_BASE_URL
    model = (payload.get("model") or "").strip() or DEFAULT_TRANSLATE_MODEL
    target_language = (payload.get("target_language") or "").strip() or DEFAULT_TARGET_LANGUAGE
    concurrency = int(payload.get("concurrency") or DEFAULT_CONCURRENCY)
    timeout_sec = DEFAULT_LLM_TIMEOUT_SEC
    return TranslatorConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        target_language=target_language,
        concurrency=concurrency,
        timeout_sec=timeout_sec,
    )


def _is_chinese_target(target_language: str) -> bool:
    lang = (target_language or "").lower()
    return ("中文" in lang) or ("chinese" in lang) or ("zh" == lang)


def _copy_project_tree(src_root: Path, dst_root: Path) -> None:
    if dst_root.exists():
        shutil.rmtree(dst_root)
    shutil.copytree(src_root, dst_root)


def _assemble_segments(segments: list[dict]) -> str:
    return "".join(seg["current"] for seg in segments)


def _recompute_segment_lines(segments: list[dict]) -> None:
    line_cursor = 1
    for seg in segments:
        seg["start_line"] = line_cursor
        line_cursor += seg["current"].count("\n")
        seg["end_line"] = line_cursor


def _find_file_state(file_states: Dict[str, Dict[str, Any]], error_file_rel: str) -> Optional[Dict[str, Any]]:
    normalized = str(error_file_rel).replace("\\", "/")
    if normalized in file_states:
        return file_states[normalized]

    as_path = Path(normalized)
    alt = as_path.as_posix()
    if alt in file_states:
        return file_states[alt]

    basename = as_path.name
    candidates = [v for k, v in file_states.items() if Path(k).name == basename]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _repair_file_state(
    *,
    file_states: Dict[str, Dict[str, Any]],
    translated_root: Path,
    error_file_rel: str,
    error_line: int,
    window: int,
) -> bool:
    state = _find_file_state(file_states, error_file_rel)
    if not state:
        return False

    line = max(1, int(error_line))
    lo = max(1, line - max(1, window))
    hi = line + max(1, window)
    changed = 0

    segments = state["segments"]
    for seg in segments:
        if not seg["translatable"]:
            continue
        if seg["current"] == seg["original"]:
            continue
        if seg["end_line"] < lo or seg["start_line"] > hi:
            continue
        seg["current"] = seg["original"]
        changed += 1

    if changed == 0:
        candidates = [
            seg
            for seg in segments
            if seg["translatable"] and (seg["current"] != seg["original"])
        ]
        if not candidates:
            return False

        def _distance(s: dict) -> int:
            if s["start_line"] <= line <= s["end_line"]:
                return 0
            if line < s["start_line"]:
                return s["start_line"] - line
            return line - s["end_line"]

        nearest = min(candidates, key=_distance)
        nearest["current"] = nearest["original"]
        changed = 1

    _recompute_segment_lines(segments)
    rel_path: Path = state["rel"]
    out_file = translated_root / rel_path
    assembled = _assemble_segments(segments)
    assembled = ensure_section_title_bold(assembled)
    out_file.write_text(assembled, encoding="utf-8")
    state["repaired_segments"] = int(state.get("repaired_segments", 0)) + changed
    return True


async def create_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    input_text = (payload.get("input_text") or "").strip()
    if not input_text:
        raise ValueError("input_text 不能为空")

    paper_id, canonical_id = resolve_arxiv_input(input_text)
    allow_cache = bool(payload.get("allow_cache", True))
    if allow_cache:
        cached = _find_cached_success_snapshot(canonical_id)
        if cached:
            return cached

    chunk_max_tokens = int(payload.get("chunk_max_tokens") or DEFAULT_CHUNK_MAX_TOKENS)
    max_compile_tries = int(payload.get("max_compile_tries") or DEFAULT_MAX_COMPILE_TRIES)

    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "status": "queued",
        "input_text": input_text,
        "paper_id": paper_id,
        "canonical_id": canonical_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "error": None,
        "steps": [],
        "artifacts": [],
        "meta": {
            "model": (payload.get("model") or DEFAULT_TRANSLATE_MODEL),
            "target_language": (payload.get("target_language") or DEFAULT_TARGET_LANGUAGE),
            "paper_title": "",
            "task_name": _build_task_name(paper_id, ""),
            "translated_chunks": 0,
            "total_chunks": 0,
            "chunk_max_tokens": chunk_max_tokens,
            "max_compile_tries": max_compile_tries,
            "compile_attempts": 0,
            "guard_fallback_chunks": 0,
        },
        "_payload": dict(payload),
        "_task": None,
        "_paths": build_job_paths(settings.ARXIV_TRANSLATE_DATA_DIR, canonical_id, job_id),
        "_cancel_requested": False,
    }

    _append_step(job, key="queued", status="done", message=f"任务已创建：arXiv:{paper_id}")
    ensure_job_dirs(job["_paths"])
    _persist_job(job)

    async with _jobs_lock:
        _jobs[job_id] = job
        job["_task"] = asyncio.create_task(_run_job(job_id))

    return _snapshot(job)


async def get_job(job_id: str) -> Dict[str, Any]:
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            return _snapshot(job)

    snap = _load_job_snapshot_from_disk(job_id)
    if snap:
        return snap
    raise KeyError("job not found")


async def cancel_job(job_id: str) -> Dict[str, Any]:
    async with _jobs_lock:
        job = _get_job(job_id)
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return _snapshot(job)
        job["_cancel_requested"] = True
        task = job.get("_task")
        if task and not task.done():
            task.cancel()
        job["status"] = "cancelled"
        _append_step(job, key="cancel", status="done", message="用户取消任务。")
        _persist_job(job)
        return _snapshot(job)


def _normalize_status_set(statuses: Optional[List[str]]) -> set[str]:
    if not statuses:
        return {"succeeded"}
    out: set[str] = set()
    for s in statuses:
        norm = str(s or "").strip().lower()
        if norm:
            out.add(norm)
    return out or {"succeeded"}


def _make_history_row_from_snapshot(snap: Dict[str, Any], *, paths: Optional[JobPaths]) -> Optional[Dict[str, Any]]:
    status = str(snap.get("status") or "")
    if not status:
        return None

    paper_id = str(
        snap.get("paper_id")
        or (paths.job_root.parent.name if paths else "")
        or (snap.get("canonical_id") or "")
    )
    canonical_id = str(
        snap.get("canonical_id")
        or (paths.job_root.parent.name if paths else "")
        or paper_id
    )
    meta = dict(snap.get("meta") or {})

    title = str(meta.get("paper_title") or "")
    if (not title) and paths and ("main_tex" in meta):
        try:
            title = _extract_paper_title_from_main_tex(paths.extract_dir, Path(str(meta["main_tex"])))
        except Exception:
            title = ""
    task_name = str(meta.get("task_name") or _build_task_name(paper_id, title))

    artifacts = []
    if paths:
        artifacts = _build_output_artifacts(paths)
    if not artifacts:
        artifacts = list(snap.get("artifacts") or [])
    if (not artifacts) and status == "succeeded":
        return None

    translated_pdf_url = _find_artifact_url(artifacts, "translate_zh.pdf")
    original_pdf_url = ""
    if paths:
        original_art = artifact_payload(
            file_path=(paths.output_dir / "original.pdf"),
            paths=paths,
            static_prefix=STATIC_PREFIX,
        )
        if (paths.output_dir / "original.pdf").exists():
            original_pdf_url = str(original_art.get("url") or "")
    if not original_pdf_url:
        original_pdf_url = str(meta.get("original_pdf_url") or "") or _original_pdf_external_url(paper_id)

    return {
        "job_id": str(snap.get("job_id") or ""),
        "status": status,
        "input_text": str(snap.get("input_text") or ""),
        "paper_id": paper_id or None,
        "canonical_id": canonical_id or None,
        "created_at": str(snap.get("created_at") or ""),
        "updated_at": str(snap.get("updated_at") or ""),
        "task_name": task_name,
        "paper_title": title or None,
        "original_pdf_url": original_pdf_url or None,
        "translated_pdf_url": translated_pdf_url or None,
        "artifacts": artifacts,
    }


async def list_jobs(limit: int = 30, statuses: Optional[List[str]] = None) -> Dict[str, Any]:
    max_items = min(max(1, int(limit)), 200)
    allowed_status = _normalize_status_set(statuses)
    base_dir = Path(settings.ARXIV_TRANSLATE_DATA_DIR)

    rows_by_id: Dict[str, Dict[str, Any]] = {}

    if base_dir.exists():
        for job_json in base_dir.glob("*/*/job.json"):
            snap = _load_disk_job_snapshot(job_json)
            if not snap:
                continue
            status = str(snap.get("status") or "").lower()
            if status not in allowed_status:
                continue
            paths = _job_paths_from_job_json(job_json)
            row = _make_history_row_from_snapshot(snap, paths=paths)
            if not row or not row.get("job_id"):
                continue
            rows_by_id[row["job_id"]] = row

    async with _jobs_lock:
        live_jobs = list(_jobs.values())

    for job in live_jobs:
        snap = _snapshot(job)
        status = str(snap.get("status") or "").lower()
        if status not in allowed_status:
            continue
        paths = job.get("_paths")
        row = _make_history_row_from_snapshot(snap, paths=paths if isinstance(paths, JobPaths) else None)
        if not row or not row.get("job_id"):
            continue
        prev = rows_by_id.get(row["job_id"])
        if not prev or str(row.get("updated_at", "")) >= str(prev.get("updated_at", "")):
            rows_by_id[row["job_id"]] = row

    rows = list(rows_by_id.values())
    rows.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"items": rows[:max_items]}


async def _run_job(job_id: str) -> None:
    job = _get_job(job_id)
    payload = job["_payload"]
    paths: JobPaths = job["_paths"]
    paper_id = job["paper_id"]
    canonical_id = job["canonical_id"]

    try:
        job["status"] = "running"
        _append_step(job, key="start", status="running", message="开始执行 arXiv 论文精细翻译。")
        _persist_job(job)

        _append_step(job, key="download", status="running", message="正在下载 arXiv 源码包...")
        _persist_job(job)
        source_url = await asyncio.to_thread(
            download_arxiv_source_archive,
            paper_id=paper_id,
            canonical_id=canonical_id,
            output_path=paths.source_archive,
            timeout_sec=DEFAULT_DOWNLOAD_TIMEOUT_SEC,
        )
        _append_step(job, key="download", status="done", message=f"源码下载完成：{source_url}")

        _append_step(job, key="extract", status="running", message="正在解压源码包...")
        _persist_job(job)
        await asyncio.to_thread(extract_source_archive, paths.source_archive, paths.extract_dir)
        project_root = await asyncio.to_thread(normalize_project_root, paths.extract_dir)
        tex_files = await asyncio.to_thread(discover_tex_files, project_root)
        main_tex_rel = await asyncio.to_thread(find_main_tex_file, project_root, tex_files)
        job["meta"]["main_tex"] = str(main_tex_rel)
        job["meta"]["tex_files"] = len(tex_files)
        paper_title = await asyncio.to_thread(_extract_paper_title_from_main_tex, project_root, main_tex_rel)
        if paper_title:
            job["meta"]["paper_title"] = paper_title
        job["meta"]["task_name"] = _build_task_name(paper_id, str(job["meta"].get("paper_title") or ""))
        _append_step(
            job,
            key="extract",
            status="done",
            message=f"源码解压完成，识别主文件：{main_tex_rel}",
        )
        _persist_job(job)

        _append_step(job, key="prepare", status="running", message="正在准备翻译工作目录...")
        await asyncio.to_thread(_copy_project_tree, project_root, paths.translated_dir)
        _append_step(job, key="prepare", status="done", message="工作目录准备完成。")
        _persist_job(job)

        translator_cfg = _resolve_client_config(payload)
        extra_prompt = (payload.get("extra_prompt") or "").strip()
        chunk_max_tokens = int(payload.get("chunk_max_tokens") or DEFAULT_CHUNK_MAX_TOKENS)
        max_chunks = DEFAULT_MAX_CHUNKS

        planned_segments: Dict[str, List[LatexSegment]] = {}
        total_chunks = 0
        for rel in tex_files:
            raw_content = (project_root / rel).read_text(encoding="utf-8", errors="ignore")
            content = strip_latex_comments(raw_content)
            segments = build_translation_segments(content, max_tokens=chunk_max_tokens)
            planned_segments[rel.as_posix()] = segments
            total_chunks += sum(1 for s in segments if s.translatable and s.text.strip())

        if total_chunks <= 0:
            raise RuntimeError("未生成可翻译分片。")
        if total_chunks > max_chunks:
            raise RuntimeError(f"论文分片过多（{total_chunks} > {max_chunks}），请提高 chunk token 大小或换更小论文。")

        job["meta"]["total_chunks"] = total_chunks
        _persist_job(job)

        _append_step(
            job,
            key="translate",
            status="running",
            message=f"开始翻译 LaTeX 内容，共 {len(tex_files)} 个 tex 文件，{total_chunks} 个分片。",
        )
        _persist_job(job)

        file_states: Dict[str, Dict[str, Any]] = {}
        translated_done = 0
        for index, rel in enumerate(tex_files, start=1):
            if job.get("_cancel_requested"):
                raise asyncio.CancelledError()

            src_file = project_root / rel
            dst_file = paths.translated_dir / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            segments = planned_segments.get(rel.as_posix())
            if segments is None:
                source_text = strip_latex_comments(src_file.read_text(encoding="utf-8", errors="ignore"))
                segments = build_translation_segments(source_text, max_tokens=chunk_max_tokens)

            state_segments: list[dict] = []
            chunks: list[str] = []
            translatable_indices: list[int] = []
            for seg in segments:
                seg_state = {
                    "original": seg.text,
                    "current": seg.text,
                    "translatable": bool(seg.translatable),
                    "start_line": seg.start_line,
                    "end_line": seg.end_line,
                }
                state_segments.append(seg_state)
                if seg.translatable and seg.text.strip():
                    translatable_indices.append(len(state_segments) - 1)
                    chunks.append(seg.text)

            if chunks:
                async def _on_progress(done: int, total: int) -> None:
                    nonlocal translated_done
                    job["meta"]["translated_chunks"] = translated_done + done
                    job["updated_at"] = _now_iso()
                    _persist_job(job)

                _append_step(
                    job,
                    key="translate_file",
                    status="running",
                    message=f"正在翻译文件 {index}/{len(tex_files)}：{rel}",
                )
                _persist_job(job)

                translated_chunks = await translate_chunks(
                    chunks,
                    translator_cfg,
                    extra_instruction=extra_prompt,
                    on_progress=_on_progress,
                )
                for seg_idx, translated in zip(translatable_indices, translated_chunks):
                    original = state_segments[seg_idx]["original"]
                    guarded = guard_translated_segment(original, translated)
                    if guarded == original and translated.strip() and translated.strip() != original.strip():
                        job["meta"]["guard_fallback_chunks"] = int(job["meta"].get("guard_fallback_chunks", 0)) + 1
                    state_segments[seg_idx]["current"] = guarded
                translated_done += len(chunks)
                job["meta"]["translated_chunks"] = translated_done
                _append_step(
                    job,
                    key="translate_file",
                    status="done",
                    message=f"文件翻译完成：{rel}",
                )
                _persist_job(job)

            _recompute_segment_lines(state_segments)
            assembled = _assemble_segments(state_segments)
            assembled = ensure_section_title_bold(assembled)
            dst_file.write_text(assembled, encoding="utf-8")
            file_states[rel.as_posix()] = {
                "rel": rel,
                "segments": state_segments,
                "repaired_segments": 0,
            }

        if _is_chinese_target(translator_cfg.target_language):
            main_tex_abs = paths.translated_dir / main_tex_rel
            injected = await asyncio.to_thread(ensure_ctex_support, main_tex_abs)
            if injected:
                _append_step(job, key="prepare_chinese", status="done", message="已自动注入 ctex 中文支持。")
                _persist_job(job)

        _append_step(job, key="compile", status="running", message="正在编译翻译后的 PDF ...")
        _persist_job(job)

        max_compile_tries = int(payload.get("max_compile_tries") or DEFAULT_MAX_COMPILE_TRIES)
        max_compile_tries = min(max(1, max_compile_tries), DEFAULT_MAX_COMPILE_TRIES)
        compile_result: Optional[Dict[str, Any]] = None
        compile_success = False
        force_compiler: Optional[str] = None
        if _is_chinese_target(translator_cfg.target_language):
            if command_exists("xelatex"):
                force_compiler = "xelatex"
            else:
                raise RuntimeError("中文翻译编译需要 xelatex，但当前环境未安装 xelatex。")

        for attempt in range(1, max_compile_tries + 1):
            if job.get("_cancel_requested"):
                raise asyncio.CancelledError()

            if _is_chinese_target(translator_cfg.target_language):
                await asyncio.to_thread(ensure_ctex_support, paths.translated_dir / main_tex_rel)

            job["meta"]["compile_attempts"] = attempt
            _append_step(
                job,
                key="compile_try",
                status="running",
                message=f"尝试第 {attempt}/{max_compile_tries} 次编译...",
            )
            _persist_job(job)

            compile_result = await asyncio.to_thread(
                compile_latex_project,
                project_root=paths.translated_dir,
                main_tex_rel=main_tex_rel,
                timeout_sec=DEFAULT_COMPILE_TIMEOUT_SEC,
                log_path=paths.output_dir / "compile.log",
                append_log=(attempt > 1),
                attempt_index=attempt,
                attempt_total=max_compile_tries,
                force_compiler=force_compiler,
            )

            if compile_result.get("compile_ok"):
                compile_success = True
                break

            first_error = compile_result.get("first_error") or {}
            err_rel = str(first_error.get("file_rel") or main_tex_rel).replace("\\", "/")
            err_line = int(first_error.get("line") or 1)
            if attempt >= max_compile_tries:
                break

            window = DEFAULT_COMPILE_REPAIR_BASE_WINDOW * attempt
            repaired = await asyncio.to_thread(
                _repair_file_state,
                file_states=file_states,
                translated_root=paths.translated_dir,
                error_file_rel=err_rel,
                error_line=err_line,
                window=window,
            )
            if repaired:
                _append_step(
                    job,
                    key="compile_fix",
                    status="running",
                    message=f"第 {attempt} 次编译失败，已回退 {err_rel}:{err_line} 附近译文并重试。",
                )
                _persist_job(job)
                continue

            _append_step(
                job,
                key="compile_fix",
                status="error",
                message=f"第 {attempt} 次编译失败，未找到可回退片段（{err_rel}:{err_line}）。",
            )
            _persist_job(job)
            break

        if not compile_success or not compile_result:
            detail = ""
            if compile_result and compile_result.get("first_error"):
                err = compile_result["first_error"]
                detail = f"{err.get('file_rel')}:{err.get('line')} {err.get('message')}"
            elif compile_result and compile_result.get("has_emergency_stop"):
                detail = "LaTeX 出现 Emergency stop，输出 PDF 可能不完整。"
            raise RuntimeError(
                f"编译失败，已尝试 {max_compile_tries} 次。{detail}".strip()
            )

        translated_pdf = await asyncio.to_thread(
            copy_file,
            Path(compile_result["pdf_path"]),
            paths.output_dir / "translate_zh.pdf",
        )
        _append_step(
            job,
            key="compile",
            status="done",
            message=f"PDF 编译完成（{compile_result['compiler']}，第 {job['meta']['compile_attempts']} 次通过）。",
        )
        _persist_job(job)

        _append_step(job, key="pack", status="running", message="正在打包翻译项目...")
        output_zip = await asyncio.to_thread(
            build_project_zip,
            paths.translated_dir,
            paths.output_dir / "project.zip",
        )
        _append_step(job, key="pack", status="done", message="打包完成。")

        artifacts = [
            artifact_payload(file_path=translated_pdf, paths=paths, static_prefix=STATIC_PREFIX),
            artifact_payload(file_path=output_zip, paths=paths, static_prefix=STATIC_PREFIX),
        ]
        compile_log = paths.output_dir / "compile.log"
        if compile_log.exists():
            artifacts.append(artifact_payload(file_path=compile_log, paths=paths, static_prefix=STATIC_PREFIX))
        job["artifacts"] = artifacts
        original_art = await asyncio.to_thread(
            _ensure_original_pdf,
            paths,
            paper_id=paper_id,
            canonical_id=canonical_id,
        )
        if original_art:
            job["meta"]["original_pdf_url"] = str(original_art.get("url") or "")
        else:
            job["meta"]["original_pdf_url"] = _original_pdf_external_url(paper_id)

        job["status"] = "succeeded"
        _append_step(job, key="done", status="done", message="任务完成，请下载译文 PDF。")
        _persist_job(job)
    except asyncio.CancelledError:
        job["status"] = "cancelled"
        _append_step(job, key="cancel", status="done", message="任务已取消。")
        _persist_job(job)
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        _append_step(job, key="error", status="error", message=f"任务失败：{exc}")
        job["meta"]["traceback"] = traceback.format_exc(limit=10)
        _persist_job(job)
