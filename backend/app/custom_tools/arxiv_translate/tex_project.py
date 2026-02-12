"""LaTeX project discovery helpers.

Review note:
- 识别解压后的有效根目录、主 tex 文件和可翻译 tex 清单。
- 采用轻量启发式，避免把模板文件误识别为主文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import List


def normalize_project_root(extract_dir: Path) -> Path:
    """
    If archive has a single wrapper directory, descend into it.
    """
    if not extract_dir.exists():
        return extract_dir
    children = [p for p in extract_dir.iterdir() if p.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        inner = children[0]
        if list(inner.rglob("*.tex")):
            return inner
    return extract_dir


def discover_tex_files(project_root: Path) -> List[Path]:
    files: List[Path] = []
    for p in project_root.rglob("*.tex"):
        rel = p.relative_to(project_root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(rel)
    files.sort(key=lambda p: str(p))
    return files


def _score_main_tex(content: str, rel_path: Path) -> int:
    score = 0
    if "\\documentclass" in content:
        score += 10
    if "\\begin{document}" in content:
        score += 6
    if "\\title{" in content:
        score += 3
    if "\\input{" in content or "\\include{" in content:
        score += 2

    lowered = content.lower()
    for keyword in ["template", "guidelines", "instruction for authors", "blind review"]:
        if keyword in lowered:
            score -= 3
    if rel_path.name.lower().startswith("merge"):
        score -= 2
    return score


def find_main_tex_file(project_root: Path, tex_files: List[Path]) -> Path:
    """
    Choose one .tex as the main entry file.
    """
    if not tex_files:
        raise RuntimeError("未找到任何 .tex 文件。")

    candidates: List[tuple[int, Path]] = []
    for rel in tex_files:
        full = project_root / rel
        content = full.read_text(encoding="utf-8", errors="ignore")
        if "\\documentclass" not in content:
            continue
        candidates.append((_score_main_tex(content, rel), rel))

    if not candidates:
        raise RuntimeError("未找到包含 \\documentclass 的主 tex 文件。")

    candidates.sort(key=lambda x: (x[0], -len(str(x[1]))), reverse=True)
    return candidates[0][1]
