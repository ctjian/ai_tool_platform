"""Parse arXiv LaTeX source package into markdown (source-first mode)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple
import re
import shutil

from app.custom_tools.arxiv_translate.downloader import (
    download_arxiv_source_archive,
    extract_source_archive,
)
from app.custom_tools.arxiv_translate.splitter import strip_latex_comments
from app.custom_tools.arxiv_translate.tex_project import (
    discover_tex_files,
    find_main_tex_file,
    normalize_project_root,
)
from app.services.sources.arxiv.tei_to_markdown import MarkdownParseResult, SectionMeta


_INCLUDE_RE = re.compile(r"\\(?:input|include)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", re.DOTALL)
_SECTION_RE = re.compile(
    r"\\(?P<cmd>section|subsection|subsubsection)\*?(?:\s*\[[^\]]*\])*\s*\{",
    re.DOTALL,
)
_LABEL_RE = re.compile(r"\\label\s*\{[^{}]*\}", re.DOTALL)
_CITE_RE = re.compile(
    r"\\(?:cite|citet|citep|citealp|citealt|citeauthor|citeyear|Cite|Citet|Citep|Citealp|Citealt|Citeauthor|Citeyear)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{[^{}]*\}",
    re.DOTALL,
)
_DEF_RE = re.compile(r"\\def\s*\\([A-Za-z@]+)\s*\{", re.DOTALL)
_NEWCOMMAND_RE = re.compile(
    r"\\(?:re)?newcommand\s*\{\\([A-Za-z@]+)\}\s*(?:\[(\d+)\])?\s*\{",
    re.DOTALL,
)


def _find_matching_brace(text: str, open_pos: int) -> int:
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "{":
        return -1
    depth = 0
    i = open_pos
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _normalize_rel_path(base_rel: str, include_target: str) -> Optional[str]:
    target = (include_target or "").strip().replace("\\", "/")
    if not target or target.startswith("/") or ":" in target:
        return None

    candidates = [target]
    if not target.endswith(".tex"):
        candidates.append(f"{target}.tex")

    base_parent = PurePosixPath(base_rel).parent
    for cand in candidates:
        merged = base_parent / PurePosixPath(cand)
        parts: List[str] = []
        ok = True
        for part in merged.parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not parts:
                    ok = False
                    break
                parts.pop()
            else:
                parts.append(part)
        if ok and parts:
            return "/".join(parts)
    return None


def _expand_includes(
    rel_path: str,
    file_map: Dict[str, str],
    *,
    memo: Dict[str, str],
    stack: set[str],
    depth: int = 0,
    max_depth: int = 32,
) -> str:
    if rel_path in memo:
        return memo[rel_path]
    if depth >= max_depth:
        return file_map.get(rel_path, "")
    if rel_path in stack:
        return ""

    source = file_map.get(rel_path, "")
    if not source:
        return ""

    stack.add(rel_path)
    cursor = 0
    out_parts: List[str] = []
    for m in _INCLUDE_RE.finditer(source):
        out_parts.append(source[cursor : m.start()])
        include_target = m.group(1)
        child_rel = _normalize_rel_path(rel_path, include_target)
        if child_rel and (child_rel in file_map):
            child_text = _expand_includes(
                child_rel,
                file_map,
                memo=memo,
                stack=stack,
                depth=depth + 1,
                max_depth=max_depth,
            )
            out_parts.append("\n")
            out_parts.append(child_text)
            out_parts.append("\n")
        cursor = m.end()
    out_parts.append(source[cursor:])
    stack.remove(rel_path)

    merged = "".join(out_parts)
    memo[rel_path] = merged
    return merged


def _extract_command_payload(text: str, command: str) -> str:
    pattern = re.compile(rf"\\{re.escape(command)}\*?(?:\s*\[[^\]]*\])*\s*\{{", re.DOTALL)
    m = pattern.search(text)
    if not m:
        return ""
    open_pos = m.end() - 1
    close_pos = _find_matching_brace(text, open_pos)
    if close_pos < 0:
        return ""
    return text[open_pos + 1 : close_pos].strip()


def _strip_labels_and_cites(text: str) -> str:
    out = _LABEL_RE.sub(" ", text or "")
    out = _CITE_RE.sub(" ", out)
    return out


def _collect_noarg_macros(text: str) -> Dict[str, str]:
    """
    Collect no-arg macro definitions from LaTeX source.
    Supported forms:
    - \\def \\foo{...}
    - \\newcommand{\\foo}{...}
    - \\renewcommand{\\foo}{...}
    """
    source = strip_latex_comments(text or "")
    macros: Dict[str, str] = {}

    for m in _DEF_RE.finditer(source):
        name = m.group(1)
        open_pos = m.end() - 1
        close_pos = _find_matching_brace(source, open_pos)
        if close_pos < 0:
            continue
        body = source[open_pos + 1 : close_pos].strip()
        if body:
            macros[name] = body

    for m in _NEWCOMMAND_RE.finditer(source):
        name = m.group(1)
        nargs = int(m.group(2) or "0")
        if nargs != 0:
            continue
        open_pos = m.end() - 1
        close_pos = _find_matching_brace(source, open_pos)
        if close_pos < 0:
            continue
        body = source[open_pos + 1 : close_pos].strip()
        if body:
            macros[name] = body

    return macros


def _expand_noarg_macros(text: str, macros: Dict[str, str]) -> str:
    if not text or not macros:
        return text or ""

    # Prefer longer names first to avoid partial replacement collisions.
    names = sorted(macros.keys(), key=len, reverse=True)
    out = text
    for _ in range(4):
        changed = False
        for name in names:
            body = macros.get(name, "")
            if not body:
                continue
            pattern = re.compile(rf"\\{re.escape(name)}(?![A-Za-z@])")
            # Use function replacement so LaTeX backslashes in macro body are kept literal.
            next_out = pattern.sub(lambda _m, rep=body: rep, out)
            if next_out != out:
                changed = True
                out = next_out
        if not changed:
            break
    return out


def _clean_meta_text(text: str, macros: Optional[Dict[str, str]] = None) -> str:
    """
    Clean short metadata text (title/section heading) into readable plain text.
    """
    out = strip_latex_comments(text or "")
    out = _expand_noarg_macros(out, macros or {})
    out = _strip_labels_and_cites(out)
    out = out.replace("\\\\", " ")
    for _ in range(8):
        next_out = re.sub(
            r"\\[a-zA-Z@]+\*?(?:\s*\[[^\]]*\])*\s*\{([^{}]*)\}",
            r"\1",
            out,
        )
        if next_out == out:
            break
        out = next_out
    out = re.sub(r"\\[a-zA-Z@]+\*?", " ", out)
    out = out.replace("\\%", "%").replace("\\_", "_").replace("\\&", "&")
    out = out.replace("{", " ").replace("}", " ").replace("~", " ")
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\s*\n\s*", " ", out)
    return out.strip()


def _clean_body_text(text: str, macros: Optional[Dict[str, str]] = None) -> str:
    """
    Keep LaTeX body mostly intact:
    - remove comments
    - remove section labels and citation commands
    - preserve formulas/environments/other commands
    """
    out = strip_latex_comments(text or "")
    out = _expand_noarg_macros(out, macros or {})
    out = _strip_labels_and_cites(out)
    out = re.sub(r"\n[ \t]+", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _extract_title(main_text: str, merged_text: str, paper_id: str, macros: Optional[Dict[str, str]] = None) -> str:
    for cmd in ["title", "icmltitle", "iclrtitle", "neuripsfinalcopytitle"]:
        payload = _extract_command_payload(main_text, cmd) or _extract_command_payload(merged_text, cmd)
        cleaned = _clean_meta_text(payload, macros)
        if cleaned:
            return cleaned[:320]
    return f"arXiv:{paper_id}"


def _extract_abstract(main_text: str, merged_text: str, macros: Optional[Dict[str, str]] = None) -> str:
    m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", merged_text, flags=re.DOTALL)
    if m:
        cleaned = _clean_body_text(m.group(1), macros)
        if cleaned:
            return cleaned
    payload = _extract_command_payload(main_text, "abstract") or _extract_command_payload(merged_text, "abstract")
    return _clean_body_text(payload, macros)


def _extract_sections(merged_text: str, macros: Optional[Dict[str, str]] = None) -> List[Tuple[int, str, str]]:
    markers: List[Dict[str, object]] = []
    for m in _SECTION_RE.finditer(merged_text):
        open_pos = m.end() - 1
        close_pos = _find_matching_brace(merged_text, open_pos)
        if close_pos < 0:
            continue
        cmd = str(m.group("cmd") or "section")
        raw_title = merged_text[open_pos + 1 : close_pos]
        title = _clean_meta_text(raw_title, macros)
        if not title:
            continue
        level = 2
        if cmd == "subsection":
            level = 3
        elif cmd == "subsubsection":
            level = 4
        markers.append(
            {
                "start": m.start(),
                "body_start": close_pos + 1,
                "title": title,
                "level": level,
            }
        )

    sections: List[Tuple[int, str, str]] = []
    for idx, marker in enumerate(markers):
        body_start = int(marker["body_start"])
        body_end = len(merged_text)
        if idx + 1 < len(markers):
            body_end = int(markers[idx + 1]["start"])
        body = _clean_body_text(merged_text[body_start:body_end], macros)
        if body:
            sections.append((int(marker["level"]), str(marker["title"]), body))

    if sections:
        return sections

    body = merged_text
    begin_doc = re.search(r"\\begin\{document\}", body)
    if begin_doc:
        body = body[begin_doc.end() :]
    end_doc = re.search(r"\\end\{document\}", body)
    if end_doc:
        body = body[: end_doc.start()]
    fallback = _clean_body_text(body, macros)
    if fallback:
        return [(2, "Body", fallback)]
    return []


def _compose_markdown(
    *,
    title: str,
    abstract: str,
    sections: List[Tuple[int, str, str]],
    markdown_path: Path,
) -> MarkdownParseResult:
    pieces: List[str] = []
    sections_meta: List[SectionMeta] = []
    cursor = 0

    def add_piece(text: str) -> None:
        nonlocal cursor
        pieces.append(text)
        cursor += len(text)

    add_piece(f"# {title}\n\n")
    if abstract:
        add_piece("## Abstract\n\n")
        add_piece(f"{abstract}\n\n")

    sec_order = 1
    for level, sec_title, sec_body in sections:
        heading_prefix = "##" if level <= 2 else "###"
        section_start = cursor
        add_piece(f"{heading_prefix} {sec_title}\n\n")
        add_piece(f"{sec_body}\n\n")
        section_end = cursor
        sections_meta.append(
            SectionMeta(
                section_id=f"s{sec_order}",
                level=level,
                title=sec_title,
                order=sec_order,
                page_start=None,
                page_end=None,
                char_start=section_start,
                char_end=section_end,
            )
        )
        sec_order += 1

    markdown = "".join(pieces).strip() + "\n"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")

    return MarkdownParseResult(
        title=title,
        abstract=abstract,
        markdown=markdown,
        sections=sections_meta,
    )


def parse_arxiv_source_to_markdown(
    *,
    paper_id: str,
    canonical_id: str,
    paper_dir: Path,
    markdown_path: Path,
    timeout_sec: int = 60,
) -> Tuple[MarkdownParseResult, Dict[str, object]]:
    """
    Parse arXiv source package into markdown.
    Returns (parsed_markdown, parse_meta).
    """
    source_root = paper_dir / "source"
    archive_path = source_root / "source_archive.bin"
    extract_dir = source_root / "extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    source_root.mkdir(parents=True, exist_ok=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    source_url = download_arxiv_source_archive(
        paper_id=paper_id,
        canonical_id=canonical_id,
        output_path=archive_path,
        timeout_sec=timeout_sec,
    )
    extract_source_archive(archive_path, extract_dir)

    project_root = normalize_project_root(extract_dir)
    tex_files = discover_tex_files(project_root)
    main_tex_rel = find_main_tex_file(project_root, tex_files)

    file_map: Dict[str, str] = {}
    for rel in tex_files:
        full = project_root / rel
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        file_map[rel.as_posix()] = strip_latex_comments(text)

    main_key = main_tex_rel.as_posix()
    if main_key not in file_map:
        raise RuntimeError("主 tex 文件读取失败。")

    merged = _expand_includes(main_key, file_map, memo={}, stack=set())
    merged = strip_latex_comments(merged)
    main_text = file_map[main_key]
    macros = _collect_noarg_macros(merged)

    title = _extract_title(main_text, merged, paper_id=paper_id, macros=macros)
    abstract = _extract_abstract(main_text, merged, macros=macros)
    sections = _extract_sections(merged, macros=macros)
    parsed = _compose_markdown(
        title=title,
        abstract=abstract,
        sections=sections,
        markdown_path=markdown_path,
    )

    # Guardrail: source parsing succeeded syntactically but yielded too little text.
    if len(parsed.markdown) < 400 or len(parsed.sections) < 1:
        raise RuntimeError("源码解析结果过短，回退到 GROBID。")

    return parsed, {
        "source_url": source_url,
        "archive_path": str(archive_path),
        "extract_dir": str(extract_dir),
        "project_root": str(project_root),
        "main_tex": main_key,
        "tex_files": [p.as_posix() for p in tex_files],
        "macro_count": len(macros),
    }
