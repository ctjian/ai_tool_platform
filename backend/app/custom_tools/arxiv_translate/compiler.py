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


def _insert_after_documentclass(text: str, block: str) -> str:
    m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", text)
    if not m:
        return text
    return text[: m.end()] + "\n" + block + "\n" + text[m.end() :]


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

    if changed:
        main_tex_path.write_text(text, encoding="utf-8")
    return changed


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
    r"(?m)^(?:\./)?(?P<file>[^\n:]+?\.tex):(?P<line>\d+):\s*(?P<msg>.+)$"
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
        if not candidate.is_absolute():
            candidate = (compile_dir / candidate).resolve()
        try:
            file_rel = str(candidate.relative_to(project_root.resolve()))
        except Exception:
            # fallback: possibly already relative to project root
            raw_posix = raw_file.replace("\\", "/")
            if (project_root / raw_posix).exists():
                file_rel = raw_posix
            else:
                file_rel = str(main_tex_rel)

        return {
            "file": raw_file,
            "file_rel": file_rel.replace("\\", "/"),
            "line": line,
            "message": msg,
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
