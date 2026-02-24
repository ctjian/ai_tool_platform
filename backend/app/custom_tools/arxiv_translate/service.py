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
    ensure_hyperref_driver_sanitized,
    ensure_hyperref_xetex,
    ensure_pdftex_compat,
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
    stabilize_zero_arg_macros_for_cjk,
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
from app.utils.pricing import compute_text_cost


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
    # Remove LaTeX line-break escapes that may pollute list titles.
    out = re.sub(r"\\\\+", " ", out)
    out = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", out)
    out = re.sub(r"\\[a-zA-Z]+\*?", " ", out)
    out = out.replace("\\", " ")
    out = out.replace("{", " ").replace("}", " ").replace("~", " ")
    out = re.sub(r"\s+", " ", out).strip()
    return out[:240]


def _extract_paper_title_from_main_tex(project_root: Path, main_tex_rel: Path) -> str:
    full = project_root / main_tex_rel
    if not full.exists():
        return ""
    text = full.read_text(encoding="utf-8", errors="ignore")
    for cmd in ["title", "TITLE", "icmltitle", "iclrtitle", "neuripsfinalcopytitle"]:
        payload = _extract_command_payload(text, cmd)
        cleaned = _clean_tex_title(payload or "")
        if cleaned:
            return cleaned
    return ""


def _build_task_name(paper_id: str, title: str) -> str:
    cleaned_title = _clean_tex_title(title)
    if cleaned_title:
        return f"arXiv:{paper_id} · {cleaned_title}"
    return f"arXiv:{paper_id}"


def _sanitize_task_name(raw: str, *, paper_id: str, title: str) -> str:
    fallback = _build_task_name(paper_id, title)
    text = str(raw or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[\\\s]+$", "", text)
    prefix = f"arXiv:{paper_id}"
    if not text.startswith(prefix):
        return fallback
    suffix = text[len(prefix):].strip()
    if suffix.startswith("·"):
        suffix = suffix[1:].strip()
    if not suffix:
        return prefix
    return _build_task_name(paper_id, suffix)


def _init_cost_meta(model: str) -> Dict[str, Any]:
    return {
        "currency": settings.PRICE_CURRENCY,
        "model": model,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
    }


def _accumulate_usage_cost(meta: Dict[str, Any], *, model: str, usage: Dict[str, int]) -> None:
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return

    cost_meta = meta.get("cost_meta")
    if not isinstance(cost_meta, dict):
        cost_meta = _init_cost_meta(model)
        meta["cost_meta"] = cost_meta

    cost_meta["prompt_tokens"] = int(cost_meta.get("prompt_tokens") or 0) + prompt_tokens
    cost_meta["completion_tokens"] = int(cost_meta.get("completion_tokens") or 0) + completion_tokens
    cost_meta["total_tokens"] = int(cost_meta.get("total_tokens") or 0) + prompt_tokens + completion_tokens

    computed = compute_text_cost(model, prompt_tokens, completion_tokens)
    if computed:
        cost_meta["currency"] = computed.get("currency") or cost_meta.get("currency") or settings.PRICE_CURRENCY
        cost_meta["model"] = computed.get("model") or model
        cost_meta["total_cost"] = float(cost_meta.get("total_cost") or 0.0) + float(computed.get("total_cost") or 0.0)


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


def _normalize_include_name(name: str, ext: str) -> str:
    clean = (name or "").strip()
    if not clean:
        return ""
    # Keep explicit suffixes (e.g. \input{foo.sty}) untouched.
    if Path(clean).suffix:
        return clean
    suffix = f".{str(ext or '').strip().lstrip('.').lower()}"
    if suffix == ".":
        return clean
    if clean.lower().endswith(suffix):
        return clean
    return f"{clean}{suffix}"


def _resolve_named_file_path(project_root: Path, include_name: str, *, ext: str) -> Optional[Path]:
    file_name = _normalize_include_name(include_name, ext)
    if not file_name:
        return None
    candidate = project_root / file_name
    if candidate.exists():
        return candidate
    matches = list(project_root.rglob(file_name))
    if matches:
        return matches[0]
    return None


def _normalize_tex_include_name(name: str) -> str:
    return _normalize_include_name(name, "tex")


def _resolve_include_tex_path(project_root: Path, include_name: str) -> Optional[Path]:
    return _resolve_named_file_path(project_root, include_name, ext="tex")


def _extract_preamble_text(text: str) -> str:
    begin_doc = re.search(r"\\begin\{document\}", text)
    return text[: begin_doc.start()] if begin_doc else text


def _find_matching_brace(text: str, open_pos: int) -> int:
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "{":
        return -1
    level = 0
    for idx in range(open_pos, len(text)):
        ch = text[idx]
        if ch == "{":
            level += 1
        elif ch == "}":
            level -= 1
            if level == 0:
                return idx
    return -1


_PREAMBLE_INCLUDE_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
_PREAMBLE_TOKEN_RE = re.compile(
    (
        r"\\(?:input|include)\s*\{([^}]+)\}"
        r"|\\(?:documentclass|LoadClass)\*?(?:\s*\[[^\]]*\])*\s*\{([^}]+)\}"
        r"|\\(?:usepackage|RequirePackage)\*?(?:\s*\[[^\]]*\])*\s*\{([^}]+)\}"
        r"|\\(?:re)?newcommand\*?\s*\{\\([A-Za-z@]+)\}"
        r"|\\(?:gdef|def)\s*\\([A-Za-z@]+)(?![A-Za-z@])"
    ),
    re.DOTALL,
)
_PREAMBLE_UNSAFE_MACRO_BODY_RE = re.compile(
    r"\\(?:def|gdef|let|futurelet|csname|expandafter|catcode)\b",
    re.DOTALL,
)
_PREAMBLE_SAFE_DEF_BODY_RE = re.compile(r"\\(?:begin|end)\s*\{[^{}]+\}\s*$", re.DOTALL)
_PREAMBLE_RESERVED_MACRO_NAMES = {
    "appendix",
    "begin",
    "caption",
    "chapter",
    "end",
    "footnote",
    "item",
    "label",
    "maketitle",
    "paragraph",
    "part",
    "ref",
    "section",
    "subparagraph",
    "subsection",
    "subsubsection",
}


def _split_latex_name_list(payload: str) -> List[str]:
    out: List[str] = []
    for chunk in (payload or "").split(","):
        item = chunk.strip()
        if item:
            out.append(item)
    return out


def _is_supported_zero_arg_macro(name: str, body: str, *, macro_kind: str) -> bool:
    macro_name = (name or "").strip()
    macro_body = (body or "").strip()
    if not macro_name or not macro_body:
        return False
    if macro_name.lower() in _PREAMBLE_RESERVED_MACRO_NAMES:
        return False
    # Skip internal commands and parameterized macro bodies.
    if "@" in macro_name or "@" in macro_body or "#" in macro_body:
        return False
    if _PREAMBLE_UNSAFE_MACRO_BODY_RE.search(macro_body):
        return False
    if macro_kind == "def":
        # For low-level \def/\gdef, only allow short begin/end wrappers like \be/\ee.
        if len(macro_name) < 2 or len(macro_name) > 8:
            return False
        if "\n" in macro_body:
            return False
        if not _PREAMBLE_SAFE_DEF_BODY_RE.fullmatch(macro_body):
            return False
    return True


def _collect_preamble_zero_arg_macros(
    project_root: Path,
    main_tex_rel: Path,
) -> tuple[Dict[str, str], Dict[str, int]]:
    """
    Collect simple 0-arg macros declared before \\begin{document}, including
    recursively imported preamble files and local class/style files loaded
    from the preamble.
    """
    macros: Dict[str, str] = {}
    stats: Dict[str, int] = {
        "files_scanned": 0,
        "files_missing_or_unreadable": 0,
        "collected_newcommand": 0,
        "collected_def": 0,
        "skipped_parameterized_or_unsupported": 0,
        "skipped_unsafe": 0,
    }
    visited: set[str] = set()

    def _walk(rel_path: Path, *, file_kind: str) -> None:
        rel_key = rel_path.as_posix()
        if rel_key in visited:
            return
        visited.add(rel_key)
        abs_path = project_root / rel_path
        if not abs_path.exists():
            stats["files_missing_or_unreadable"] += 1
            return
        try:
            raw = abs_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            stats["files_missing_or_unreadable"] += 1
            return
        stats["files_scanned"] += 1

        text = strip_latex_comments(raw)
        if file_kind == "tex":
            text = _extract_preamble_text(text)
        cursor = 0
        while cursor < len(text):
            m = _PREAMBLE_TOKEN_RE.search(text, cursor)
            if not m:
                break

            include_name = (m.group(1) or "").strip()
            class_payload = (m.group(2) or "").strip()
            package_payload = (m.group(3) or "").strip()
            newcommand_name = (m.group(4) or "").strip()
            def_name = (m.group(5) or "").strip()
            if include_name:
                inc_abs = _resolve_include_tex_path(project_root, include_name)
                if inc_abs is not None:
                    try:
                        _walk(inc_abs.relative_to(project_root), file_kind="tex")
                    except Exception:
                        pass
                cursor = m.end()
                continue

            if class_payload:
                for class_name in _split_latex_name_list(class_payload):
                    cls_abs = _resolve_named_file_path(project_root, class_name, ext="cls")
                    if cls_abs is None:
                        continue
                    try:
                        _walk(cls_abs.relative_to(project_root), file_kind="cls")
                    except Exception:
                        pass
                cursor = m.end()
                continue

            if package_payload:
                for package_name in _split_latex_name_list(package_payload):
                    sty_abs = _resolve_named_file_path(project_root, package_name, ext="sty")
                    if sty_abs is None:
                        continue
                    try:
                        _walk(sty_abs.relative_to(project_root), file_kind="sty")
                    except Exception:
                        pass
                cursor = m.end()
                continue

            if not newcommand_name and not def_name:
                cursor = m.end()
                continue

            idx = m.end()
            while idx < len(text) and text[idx].isspace():
                idx += 1

            if newcommand_name:
                # Ignore parameterized forms, e.g. \newcommand{\foo}[2]{...}.
                if idx < len(text) and text[idx] == "[":
                    stats["skipped_parameterized_or_unsupported"] += 1
                    bracket_end = text.find("]", idx + 1)
                    cursor = (bracket_end + 1) if bracket_end >= 0 else m.end()
                    continue

            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text) or text[idx] != "{":
                stats["skipped_parameterized_or_unsupported"] += 1
                cursor = m.end()
                continue

            body_end = _find_matching_brace(text, idx)
            if body_end < 0:
                stats["skipped_parameterized_or_unsupported"] += 1
                cursor = m.end()
                continue

            body = text[idx + 1 : body_end].strip()
            macro_name = newcommand_name or def_name
            macro_kind = "newcommand" if newcommand_name else "def"
            if body and _is_supported_zero_arg_macro(macro_name, body, macro_kind=macro_kind):
                macros[macro_name] = body
                if newcommand_name:
                    stats["collected_newcommand"] += 1
                else:
                    stats["collected_def"] += 1
            elif body:
                stats["skipped_unsafe"] += 1
            cursor = body_end + 1

    _walk(main_tex_rel, file_kind="tex")
    return macros, stats


def _expand_zero_arg_macros_from_preamble(
    text: str,
    macro_map: Dict[str, str],
    *,
    only_after_begin_document: bool,
) -> str:
    if not text or not macro_map:
        return text

    ordered_names = sorted(macro_map.keys(), key=len, reverse=True)

    def _replace(chunk: str) -> str:
        out = chunk
        for name in ordered_names:
            pattern = re.compile(rf"\\{re.escape(name)}(?![A-Za-z@])")
            replacement_body = macro_map[name].strip()
            # Wrapping \begin/\end in braces breaks environment pairing, e.g. {\begin{equation}}.
            if _PREAMBLE_SAFE_DEF_BODY_RE.fullmatch(replacement_body):
                replacement = replacement_body
            else:
                replacement = "{" + replacement_body + "}"
            out = pattern.sub(lambda _m, rep=replacement: rep, out)
        return out

    if only_after_begin_document:
        begin_doc = re.search(r"\\begin\{document\}", text)
        if not begin_doc:
            return text
        head = text[: begin_doc.end()]
        tail = text[begin_doc.end() :]
        return head + _replace(tail)

    return _replace(text)


def _collect_preamble_tex_files(project_root: Path, main_tex_rel: Path) -> set[str]:
    """
    Identify tex files included before \\begin{document} in the main tex.
    These files belong to the preamble and should not be translated.
    """
    main_tex = project_root / main_tex_rel
    if not main_tex.exists():
        return set()

    try:
        raw = main_tex.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return set()

    preamble_text = _extract_preamble_text(strip_latex_comments(raw))
    queue: list[str] = []
    for m in _PREAMBLE_INCLUDE_RE.finditer(preamble_text):
        name = (m.group(1) or "").strip()
        if name:
            queue.append(name)

    collected: set[str] = set()
    visited: set[str] = set()

    while queue:
        name = queue.pop()
        if name in visited:
            continue
        visited.add(name)
        candidate = _resolve_include_tex_path(project_root, name)
        if candidate is None:
            continue
        rel = candidate.relative_to(project_root).as_posix()
        if rel in collected:
            continue
        collected.add(rel)

        try:
            sub_text = strip_latex_comments(candidate.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for m in _PREAMBLE_INCLUDE_RE.finditer(sub_text):
            sub_name = (m.group(1) or "").strip()
            if sub_name:
                queue.append(sub_name)

    return collected


def _copy_precompile_tex_files(*, src_root: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for tex_path in src_root.rglob("*.tex"):
        rel = tex_path.relative_to(src_root)
        dst = output_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tex_path, dst)


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
    assembled = stabilize_zero_arg_macros_for_cjk(assembled)
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
    model_name = str(payload.get("model") or DEFAULT_TRANSLATE_MODEL)
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
            "model": model_name,
            "target_language": (payload.get("target_language") or DEFAULT_TARGET_LANGUAGE),
            "paper_title": "",
            "task_name": _build_task_name(paper_id, ""),
            "translated_chunks": 0,
            "total_chunks": 0,
            "chunk_max_tokens": chunk_max_tokens,
            "max_compile_tries": max_compile_tries,
            "compile_attempts": 0,
            "guard_fallback_chunks": 0,
            "request_count": 0,
            "cost_meta": _init_cost_meta(model_name),
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

    title = _clean_tex_title(str(meta.get("paper_title") or ""))
    extracted_title = ""
    if paths and ("main_tex" in meta):
        try:
            extracted_title = _extract_paper_title_from_main_tex(paths.extract_dir, Path(str(meta["main_tex"])))
        except Exception:
            extracted_title = ""
    if extracted_title:
        title = extracted_title
    task_name = _build_task_name(paper_id, title) if title else _sanitize_task_name(
        str(meta.get("task_name") or ""),
        paper_id=paper_id,
        title="",
    )

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
        "cost_meta": meta.get("cost_meta"),
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
        preamble_tex_files = _collect_preamble_tex_files(project_root, main_tex_rel)
        preamble_zero_arg_macros, preamble_macro_stats = _collect_preamble_zero_arg_macros(
            project_root,
            main_tex_rel,
        )
        job["meta"]["preamble_zero_arg_macro_count"] = len(preamble_zero_arg_macros)
        job["meta"]["preamble_zero_arg_macro_stats"] = preamble_macro_stats
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
            rel_key = rel.as_posix()
            if rel_key in preamble_tex_files:
                line_count = raw_content.count("\n")
                segments = [
                    LatexSegment(
                        text=raw_content,
                        translatable=False,
                        start_line=1,
                        end_line=1 + line_count,
                    )
                ]
            else:
                content = strip_latex_comments(raw_content)
                content = _expand_zero_arg_macros_from_preamble(
                    content,
                    preamble_zero_arg_macros,
                    only_after_begin_document=(rel == main_tex_rel),
                )
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
        usage_lock = asyncio.Lock()
        for index, rel in enumerate(tex_files, start=1):
            if job.get("_cancel_requested"):
                raise asyncio.CancelledError()

            src_file = project_root / rel
            dst_file = paths.translated_dir / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            rel_key = rel.as_posix()
            segments = planned_segments.get(rel_key)
            if segments is None:
                if rel_key in preamble_tex_files:
                    raw_text = src_file.read_text(encoding="utf-8", errors="ignore")
                    line_count = raw_text.count("\n")
                    segments = [
                        LatexSegment(
                            text=raw_text,
                            translatable=False,
                            start_line=1,
                            end_line=1 + line_count,
                        )
                    ]
                else:
                    source_text = strip_latex_comments(src_file.read_text(encoding="utf-8", errors="ignore"))
                    source_text = _expand_zero_arg_macros_from_preamble(
                        source_text,
                        preamble_zero_arg_macros,
                        only_after_begin_document=(rel == main_tex_rel),
                    )
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

                async def _on_usage(usage: Dict[str, int]) -> None:
                    async with usage_lock:
                        _accumulate_usage_cost(job["meta"], model=translator_cfg.model, usage=usage)
                        job["meta"]["request_count"] = int(job["meta"].get("request_count") or 0) + 1
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
                    on_usage=_on_usage,
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
            assembled = stabilize_zero_arg_macros_for_cjk(assembled)
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
            hyperref_forced = await asyncio.to_thread(ensure_hyperref_xetex, main_tex_abs)
            if hyperref_forced:
                _append_step(job, key="prepare_hyperref", status="done", message="已强制 hyperref 使用 XeTeX 驱动。")
                _persist_job(job)
            await asyncio.to_thread(ensure_hyperref_driver_sanitized, paths.translated_dir)

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

        if force_compiler == "xelatex":
            await asyncio.to_thread(ensure_pdftex_compat, paths.translated_dir)

        _append_step(job, key="snapshot", status="running", message="正在保存编译前 tex 版本...")
        _persist_job(job)
        await asyncio.to_thread(
            _copy_precompile_tex_files,
            src_root=paths.translated_dir,
            output_dir=paths.output_dir / "precompile_tex",
        )
        _append_step(job, key="snapshot", status="done", message="已保存编译前 tex 版本。")
        _persist_job(job)

        for attempt in range(1, max_compile_tries + 1):
            if job.get("_cancel_requested"):
                raise asyncio.CancelledError()

            if _is_chinese_target(translator_cfg.target_language):
                await asyncio.to_thread(ensure_ctex_support, paths.translated_dir / main_tex_rel)
                await asyncio.to_thread(ensure_hyperref_xetex, paths.translated_dir / main_tex_rel)
                await asyncio.to_thread(ensure_hyperref_driver_sanitized, paths.translated_dir)
                await asyncio.to_thread(ensure_pdftex_compat, paths.translated_dir)

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
        precompile_dir = paths.output_dir / "precompile_tex"
        if precompile_dir.exists():
            for tex_path in sorted(precompile_dir.rglob("*.tex")):
                artifacts.append(
                    artifact_payload(file_path=tex_path, paths=paths, static_prefix=STATIC_PREFIX)
                )
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
