"""LaTeX compile helpers for translated projects."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import re
import shutil
import subprocess
import zipfile


def detect_compiler(main_tex_path: Path) -> str:
    content = main_tex_path.read_text(encoding="utf-8", errors="ignore")[:8000]
    markers = ["fontspec", "xeCJK", "xetex", "unicode-math", "xltxtra", "xunicode", "ctex"]
    if any(m in content for m in markers):
        if command_exists("xelatex"):
            return "xelatex"
    return "pdflatex"


def command_exists(name: str) -> bool:
    try:
        subprocess.run([name, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=6)
        return True
    except Exception:
        return False


_CJK_FALLBACK_BEGIN = "%% ARXIV_TRANSLATE_CJK_FONT_FALLBACK_BEGIN"
_CJK_FALLBACK_END = "%% ARXIV_TRANSLATE_CJK_FONT_FALLBACK_END"
_CJK_FALLBACK_BLOCK = rf"""
{_CJK_FALLBACK_BEGIN}
\ifdefined\XeTeXversion
\providecommand{{\pdfinfo}}[1]{{}}
\makeatletter
\@ifundefined{{IfFontExistsTF}}{{}}{{%
  \@ifundefined{{setCJKmainfont}}{{}}{{%
    \IfFontExistsTF{{Noto Serif CJK SC}}{{\setCJKmainfont{{Noto Serif CJK SC}}}}{{%
      \IfFontExistsTF{{Source Han Serif SC}}{{\setCJKmainfont{{Source Han Serif SC}}}}{{%
        \IfFontExistsTF{{AR PL UMing CN}}{{\setCJKmainfont{{AR PL UMing CN}}}}{{%
          \IfFontExistsTF{{Droid Sans Fallback}}{{\setCJKmainfont{{Droid Sans Fallback}}}}{{}}%
        }}%
      }}%
    }}%
    \IfFontExistsTF{{Noto Sans CJK SC}}{{\setCJKsansfont{{Noto Sans CJK SC}}}}{{%
      \IfFontExistsTF{{Source Han Sans SC}}{{\setCJKsansfont{{Source Han Sans SC}}}}{{}}%
    }}%
    \IfFontExistsTF{{Noto Sans Mono CJK SC}}{{\setCJKmonofont{{Noto Sans Mono CJK SC}}}}{{}}%
  }}%
}}
\makeatother
\fi
{_CJK_FALLBACK_END}
""".strip()


_INPUTENC_RE = re.compile(
    r"(?m)^[ \t]*\\usepackage(?:\[[^\]]*\])?\{inputenc\}[ \t]*\n?"
)
_FONTENC_RE = re.compile(
    r"(?m)^[ \t]*\\usepackage(?:\[[^\]]*\])?\{fontenc\}[ \t]*\n?"
)
_MICROTYPE_RE = re.compile(
    r"(?m)^[ \t]*\\usepackage(?:\[[^\]]*\])?\{microtype\}[ \t]*\n?"
)

_PDFTEX_COMPAT_BEGIN = "%% ARXIV_TRANSLATE_PDFTEX_COMPAT_BEGIN"
_PDFTEX_COMPAT_END = "%% ARXIV_TRANSLATE_PDFTEX_COMPAT_END"
_PDFTEX_COMPAT_BLOCK = rf"""
{_PDFTEX_COMPAT_BEGIN}
\makeatletter
\@ifundefined{{pdfoutput}}{{\newcount\pdfoutput}}{{}}%
\@ifundefined{{pdfminorversion}}{{\newcount\pdfminorversion}}{{}}%
\@ifundefined{{pdfpagewidth}}{{\newdimen\pdfpagewidth}}{{}}%
\@ifundefined{{pdfpageheight}}{{\newdimen\pdfpageheight}}{{}}%
\@ifundefined{{pdfhorigin}}{{\newdimen\pdfhorigin}}{{}}%
\@ifundefined{{pdfvorigin}}{{\newdimen\pdfvorigin}}{{}}%
\@ifundefined{{pdfpagesattr}}{{\def\pdfpagesattr#1{{}}}}{{}}%
\@ifundefined{{pdfcatalog}}{{\def\pdfcatalog#1{{}}}}{{}}%
\@ifundefined{{pdfdest}}{{\def\pdfdest#1{{}}}}{{}}%
{_PDFTEX_COMPAT_END}
""".strip()

_PDFTEX_PRIMITIVE_HINTS = (
    "\\pdfoutput",
    "\\pdfminorversion",
    "\\pdfpagewidth",
    "\\pdfpageheight",
    "\\pdfhorigin",
    "\\pdfvorigin",
    "\\pdfpagesattr",
    "\\pdfcatalog",
    "\\pdfdest",
)

_SUBCAPTION_COMPAT_BEGIN = "%% ARXIV_TRANSLATE_SUBCAPTION_COMPAT_BEGIN"
_SUBCAPTION_COMPAT_END = "%% ARXIV_TRANSLATE_SUBCAPTION_COMPAT_END"
_USEPACKAGE_SUBCAPTION_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)\\usepackage(?:\[[^\]]*\])?\{subcaption\}[ \t]*$"
)


def _insert_after_documentclass(text: str, block: str) -> str:
    m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", text)
    if not m:
        return text
    return text[: m.end()] + "\n" + block + "\n" + text[m.end() :]


def _insert_before_documentclass(text: str, block: str) -> str:
    m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", text)
    if not m:
        return text
    return text[: m.start()] + block + "\n" + text[m.start() :]


def _insert_after_ctex_package(text: str, block: str) -> str:
    ctex_re = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{ctex\}")
    m = ctex_re.search(text)
    if not m:
        return _insert_after_documentclass(text, block)
    return text[: m.end()] + "\n" + block + "\n" + text[m.end() :]


def ensure_ctex_support(main_tex_path: Path) -> bool:
    """
    Ensure Chinese-capable XeLaTeX preamble exists and is stable after retries.
    Returns True when file changed.
    """
    text = main_tex_path.read_text(encoding="utf-8", errors="replace")
    changed = False

    has_ctex = ("\\usepackage{ctex}" in text) or ("\\usepackage[UTF8]{ctex}" in text)
    if not has_ctex:
        updated = _insert_after_documentclass(text, "\\usepackage[UTF8]{ctex}")
        if updated == text:
            return False
        text = updated
        changed = True

    if _CJK_FALLBACK_BEGIN not in text:
        text = _insert_after_ctex_package(text, _CJK_FALLBACK_BLOCK)
        changed = True

    if "{url}" not in text:
        text = _insert_after_ctex_package(text, "\\usepackage{url}")
        changed = True

    # xelatex/ctex 下 inputenc 会报错并导致返回码非 0，触发无意义重试
    if _INPUTENC_RE.search(text):
        text = _INPUTENC_RE.sub("", text)
        changed = True

    # XeLaTeX + legacy T1/microtype on Times(Type1) fonts may trigger:
    # "Cannot use XeTeXglyph with ptmr8c/ptmri8c; not a native platform font."
    if _FONTENC_RE.search(text):
        text = _FONTENC_RE.sub("", text)
        changed = True
    if _MICROTYPE_RE.search(text):
        text = _MICROTYPE_RE.sub("", text)
        changed = True

    if changed:
        main_tex_path.write_text(text, encoding="utf-8")
    return changed


_HYPERREF_XETEX_LINE = r"\PassOptionsToPackage{xetex}{hyperref}"
_HYPERREF_DRIVER_OPTIONS = {
    "pdftex",
    "dvips",
    "dvipdfm",
    "dvipdfmx",
    "dviwindo",
    "vtex",
    "hypertex",
}


def ensure_hyperref_xetex(main_tex_path: Path) -> bool:
    """
    Force hyperref to use the XeTeX driver before it is loaded.
    Returns True when file changed.
    """
    text = main_tex_path.read_text(encoding="utf-8", errors="replace")
    changed = False
    if _HYPERREF_XETEX_LINE not in text:
        updated = _insert_before_documentclass(text, _HYPERREF_XETEX_LINE)
        if updated != text:
            text = updated
            changed = True

    updated, stripped = _strip_hyperref_driver_options(text)
    if stripped:
        text = updated
        changed = True

    if changed:
        main_tex_path.write_text(text, encoding="utf-8")
    return changed


def _split_option_list(options: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    for ch in options:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            item = "".join(buf).strip()
            if item:
                parts.append(item)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _strip_driver_options_from_list(options: str) -> tuple[str, bool]:
    parts = _split_option_list(options)
    kept: List[str] = []
    changed = False
    for part in parts:
        lower = part.lower()
        if lower in _HYPERREF_DRIVER_OPTIONS:
            changed = True
            continue
        if lower.startswith("driver="):
            driver = lower.split("=", 1)[1].strip()
            if driver in _HYPERREF_DRIVER_OPTIONS:
                changed = True
                continue
        kept.append(part)
    return (", ".join(kept), changed)


def _strip_hyperref_driver_options(text: str) -> tuple[str, bool]:
    changed = False

    def _replace_passoptions(match: re.Match) -> str:
        nonlocal changed
        opts = match.group(1)
        new_opts, stripped = _strip_driver_options_from_list(opts)
        if not stripped:
            return match.group(0)
        changed = True
        if not new_opts:
            return ""
        return f"\\PassOptionsToPackage{{{new_opts}}}{{hyperref}}"

    text = re.sub(
        r"\\PassOptionsToPackage\s*\{([^}]*)\}\s*\{hyperref\}",
        _replace_passoptions,
        text,
    )

    def _replace_usepackage(match: re.Match) -> str:
        nonlocal changed
        cmd = match.group("cmd")
        opts = match.group("opts")
        if not opts:
            return match.group(0)
        new_opts, stripped = _strip_driver_options_from_list(opts)
        if not stripped:
            return match.group(0)
        changed = True
        if not new_opts:
            return f"{cmd}{{hyperref}}"
        return f"{cmd}[{new_opts}]{{hyperref}}"

    pattern = re.compile(
        r"(?P<cmd>\\(?:usepackage|RequirePackage))\s*(?:\[(?P<opts>[^\]]*)\])?\s*\{hyperref\}"
    )
    text = pattern.sub(_replace_usepackage, text)

    return text, changed


def ensure_hyperref_driver_sanitized(project_root: Path) -> int:
    """Strip hyperref driver options (pdftex/dvips/...) from project files."""
    patched = 0
    for ext in (".tex", ".sty", ".cls"):
        for path in project_root.rglob(f"*{ext}"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            updated, changed = _strip_hyperref_driver_options(text)
            if not changed:
                continue
            try:
                path.write_text(updated, encoding="utf-8")
                patched += 1
            except Exception:
                continue
    return patched


def _insert_pdftex_compat_block(text: str) -> tuple[str, bool]:
    if _PDFTEX_COMPAT_BEGIN in text and _PDFTEX_COMPAT_END in text:
        pattern = re.compile(
            rf"{re.escape(_PDFTEX_COMPAT_BEGIN)}.*?{re.escape(_PDFTEX_COMPAT_END)}",
            re.DOTALL,
        )
        updated = pattern.sub(lambda _m: _PDFTEX_COMPAT_BLOCK, text)
        return updated, updated != text
    if not any(token in text for token in _PDFTEX_PRIMITIVE_HINTS):
        return text, False

    lines = text.splitlines()
    insert_at = 0
    header_re = re.compile(r"\\(NeedsTeXFormat|ProvidesPackage|ProvidesClass|ProvidesFile)\b")
    for idx, line in enumerate(lines[:80]):
        if header_re.search(line):
            insert_at = idx + 1
    injected = (
        lines[:insert_at]
        + ([""] if insert_at > 0 else [])
        + [_PDFTEX_COMPAT_BLOCK, ""]
        + lines[insert_at:]
    )
    return "\n".join(injected), True


def ensure_pdftex_compat(project_root: Path) -> int:
    """Patch pdfTeX-only primitives for XeLaTeX/LuaLaTeX compatibility."""
    patched = 0
    for ext in (".sty", ".cls"):
        for path in project_root.rglob(f"*{ext}"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            updated, changed = _insert_pdftex_compat_block(text)
            if not changed:
                continue
            try:
                path.write_text(updated, encoding="utf-8")
                patched += 1
            except Exception:
                continue
    return patched


def ensure_subcaption_compat(main_tex_path: Path) -> bool:
    """
    subcaption cannot coexist with legacy subfigure. Some arXiv sources load both
    even though the document only uses \subfigure. In that case we disable
    subcaption conservatively to preserve original behavior.
    """
    text = main_tex_path.read_text(encoding="utf-8", errors="replace")
    if _SUBCAPTION_COMPAT_BEGIN in text and _SUBCAPTION_COMPAT_END in text:
        return False

    has_subfigure_pkg = bool(re.search(r"\\usepackage(?:\[[^\]]*\])?\{subfigure\}", text))
    has_subcaption_pkg = bool(re.search(r"\\usepackage(?:\[[^\]]*\])?\{subcaption\}", text))
    uses_subfigure_cmd = "\\subfigure" in text
    uses_subcaption_cmd = any(token in text for token in ("\\subcaption", "\\subcaptionbox", "\\begin{subfigure}"))

    if not (has_subfigure_pkg and has_subcaption_pkg and uses_subfigure_cmd and not uses_subcaption_cmd):
        return False

    changed = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        indent = match.group("indent") or ""
        return (
            f"{indent}{_SUBCAPTION_COMPAT_BEGIN}\n"
            f"{indent}% disabled automatically: incompatible with subfigure package\n"
            f"{indent}% {match.group(0).lstrip()}\n"
            f"{indent}{_SUBCAPTION_COMPAT_END}"
        )

    updated = _USEPACKAGE_SUBCAPTION_RE.sub(_replace, text, count=1)
    if not changed or updated == text:
        return False

    main_tex_path.write_text(updated, encoding="utf-8")
    return True


def _run_command(
    cmd: List[str],
    *,
    cwd: Path,
    timeout_sec: int,
    log_fp,
) -> Dict[str, int | bool]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_sec,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = proc.stdout or ""
        return_code = int(proc.returncode)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\n[timeout]\n" + (exc.stderr or "")
        return_code = 124
        timed_out = True
    except FileNotFoundError as exc:
        raise RuntimeError(f"命令不存在：{cmd[0]}") from exc

    log_fp.write(f"$ {' '.join(cmd)}\n")
    log_fp.write(output)
    log_fp.write("\n\n")
    return {"returncode": return_code, "timed_out": timed_out, "output": output}


def _bbl_has_entries(bbl_file: Path) -> bool:
    if not bbl_file.exists():
        return False
    try:
        text = bbl_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return ("\\bibitem" in text) and (len(text.strip()) > 80)


_ERROR_RE = re.compile(
    r"(?m)^(?:\./)?(?P<file>[^\n:]+?\.(?:tex|sty|cls|bst|bib)):"
    r"(?P<line>\d+):\s*(?P<msg>.+)$"
)


def parse_first_latex_error(
    log_text: str,
    *,
    compile_dir: Path,
    project_root: Path,
    main_tex_rel: Path,
) -> Optional[Dict[str, str | int]]:
    m = _ERROR_RE.search(log_text)
    if m:
        raw_file = m.group("file").strip()
        line = int(m.group("line"))
        msg = m.group("msg").strip()
        file_rel: Optional[str] = None

        candidate = Path(raw_file)
        project_root_resolved = project_root.resolve()
        if not candidate.is_absolute():
            candidate = (compile_dir / candidate).resolve()
        try:
            file_rel = str(candidate.relative_to(project_root_resolved))
        except Exception:
            # fallback: possibly already relative to project root
            raw_posix = raw_file.replace("\\", "/")
            if (project_root / raw_posix).exists():
                file_rel = raw_posix
            else:
                file_rel = str(main_tex_rel)

        # External TeX Live style/class files are not repairable by segment rollback.
        # Report them, but attribute fallback location to main tex so the caller can
        # treat them as compatibility/package issues instead of local text corruption.
        if candidate.is_absolute():
            try:
                candidate.relative_to(project_root_resolved)
            except Exception:
                return {
                    "file": raw_file,
                    "file_rel": str(main_tex_rel).replace("\\", "/"),
                    "line": line,
                    "message": msg,
                    "external_file": raw_file,
                    "external": True,
                }

        return {
            "file": raw_file,
            "file_rel": file_rel.replace("\\", "/"),
            "line": line,
            "message": msg,
            "external": False,
        }

    fallback = re.search(r"(?m)^l\.(?P<line>\d+)\b", log_text)
    if fallback:
        return {
            "file": str(main_tex_rel),
            "file_rel": str(main_tex_rel).replace("\\", "/"),
            "line": int(fallback.group("line")),
            "message": "无法定位 tex 文件，使用主文件行号回退。",
        }
    return None


def compile_latex_project(
    *,
    project_root: Path,
    main_tex_rel: Path,
    timeout_sec: int = 180,
    log_path: Path | None = None,
    append_log: bool = False,
    attempt_index: int | None = None,
    attempt_total: int | None = None,
    force_compiler: str | None = None,
) -> Dict:
    main_tex_abs = project_root / main_tex_rel
    if not main_tex_abs.exists():
        raise RuntimeError(f"主 tex 不存在: {main_tex_rel}")

    compile_dir = main_tex_abs.parent
    main_stem = main_tex_abs.stem
    compiler = force_compiler or detect_compiler(main_tex_abs)
    log_file = log_path or (project_root / "compile.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    pdf_path = compile_dir / f"{main_stem}.pdf"
    if pdf_path.exists():
        pdf_path.unlink()

    mode = "a" if append_log and log_file.exists() else "w"
    return_codes: List[int] = []
    timed_out = False
    attempt_log_chunks: List[str] = []

    with log_file.open(mode, encoding="utf-8") as log_fp:
        if mode == "a":
            log_fp.write("\n\n")
        if attempt_index is not None and attempt_total is not None:
            log_fp.write(f"===== Compile Attempt {attempt_index}/{attempt_total} =====\n")
        else:
            log_fp.write("===== Compile Attempt =====\n")

        bbl_file = compile_dir / f"{main_stem}.bbl"
        keep_existing_bbl = _bbl_has_entries(bbl_file)
        if keep_existing_bbl:
            log_fp.write(f"[info] keep existing bbl: {bbl_file.name}\n\n")

        first = _run_command(
            [compiler, "-interaction=nonstopmode", "-file-line-error", f"{main_stem}.tex"],
            cwd=compile_dir,
            timeout_sec=timeout_sec,
            log_fp=log_fp,
        )
        return_codes.append(int(first["returncode"]))
        timed_out = timed_out or bool(first["timed_out"])
        attempt_log_chunks.append(str(first.get("output") or ""))

        aux_file = compile_dir / f"{main_stem}.aux"
        if aux_file.exists() and (not keep_existing_bbl):
            bib = _run_command(
                ["bibtex", main_stem],
                cwd=compile_dir,
                timeout_sec=timeout_sec,
                log_fp=log_fp,
            )
            return_codes.append(int(bib["returncode"]))
            timed_out = timed_out or bool(bib["timed_out"])
            attempt_log_chunks.append(str(bib.get("output") or ""))

        second = _run_command(
            [compiler, "-interaction=nonstopmode", "-file-line-error", f"{main_stem}.tex"],
            cwd=compile_dir,
            timeout_sec=timeout_sec,
            log_fp=log_fp,
        )
        return_codes.append(int(second["returncode"]))
        timed_out = timed_out or bool(second["timed_out"])
        attempt_log_chunks.append(str(second.get("output") or ""))

        third = _run_command(
            [compiler, "-interaction=nonstopmode", "-file-line-error", f"{main_stem}.tex"],
            cwd=compile_dir,
            timeout_sec=timeout_sec,
            log_fp=log_fp,
        )
        return_codes.append(int(third["returncode"]))
        timed_out = timed_out or bool(third["timed_out"])
        attempt_log_chunks.append(str(third.get("output") or ""))

    log_text = "\n".join(attempt_log_chunks)
    first_error = parse_first_latex_error(
        log_text,
        compile_dir=compile_dir,
        project_root=project_root,
        main_tex_rel=main_tex_rel,
    )

    pdf_exists = pdf_path.exists() and pdf_path.stat().st_size > 0
    has_emergency_stop = bool(re.search(r"(?im)^!\s*Emergency stop\.", log_text))
    last_ok = bool(return_codes) and int(return_codes[-1]) == 0
    compile_ok = bool(pdf_exists and last_ok and (not has_emergency_stop))
    return {
        "compiler": compiler,
        "pdf_path": str(pdf_path),
        "pdf_exists": pdf_exists,
        "compile_ok": compile_ok,
        "has_emergency_stop": has_emergency_stop,
        "log_path": str(log_file),
        "return_codes": return_codes,
        "timed_out": timed_out,
        "first_error": first_error,
    }


def build_project_zip(source_dir: Path, output_zip: Path) -> Path:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in source_dir.rglob("*"):
            if not file_path.is_file():
                continue
            arcname = file_path.relative_to(source_dir)
            zf.write(file_path, arcname=str(arcname))
    return output_zip


def copy_file(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst
