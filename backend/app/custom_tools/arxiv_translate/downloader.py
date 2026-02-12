"""arXiv source downloader for latex translation jobs.

Review note:
- 解析输入中的 arXiv URL/ID，并下载源码包（src/e-print）。
- 提供安全解压，避免路径穿越。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
import tarfile
import zipfile

import httpx

from app.services.sources.arxiv.id_parser import extract_arxiv_targets, normalize_arxiv_id


def resolve_arxiv_input(raw: str) -> Tuple[str, str]:
    """
    Resolve user input into (paper_id_with_version, canonical_id_without_version).
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("请输入 arXiv 链接或 ID。")

    targets = extract_arxiv_targets(text, max_refs=1)
    if targets:
        target = targets[0]
        return target.paper_id, target.canonical_id

    normalized = normalize_arxiv_id(text)
    if normalized:
        return normalized[0], normalized[1]

    raise ValueError("无法识别 arXiv 链接或 ID。")


def download_arxiv_source_archive(
    *,
    paper_id: str,
    canonical_id: str,
    output_path: Path,
    timeout_sec: int = 60,
) -> str:
    """
    Download arXiv source archive to output_path.
    Returns the final source URL used.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_ids = [paper_id]
    if canonical_id and canonical_id not in candidate_ids:
        candidate_ids.append(canonical_id)

    candidate_urls = []
    for pid in candidate_ids:
        candidate_urls.append(f"https://arxiv.org/src/{pid}")
        candidate_urls.append(f"https://arxiv.org/e-print/{pid}")

    with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
        last_error: Optional[str] = None
        for url in candidate_urls:
            try:
                resp = client.get(url)
            except httpx.HTTPError as exc:
                last_error = f"{url}: {exc}"
                continue

            if resp.status_code >= 400 or not resp.content:
                last_error = f"{url}: status={resp.status_code}"
                continue

            content_type = (resp.headers.get("content-type") or "").lower()
            body_head = resp.text[:500].lower() if "text/" in content_type else ""
            if "text/html" in content_type and ("no source" in body_head or "abs/" in body_head):
                last_error = f"{url}: no source package available"
                continue

            output_path.write_bytes(resp.content)
            return url

    raise RuntimeError(f"下载 arXiv 源码失败：{last_error or 'unknown error'}")


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except Exception:
        return False


def _safe_extract_tar(tar: tarfile.TarFile, dest_dir: Path) -> None:
    dest_dir_resolved = dest_dir.resolve()
    for member in tar.getmembers():
        member_path = dest_dir / member.name
        if not _is_within(dest_dir_resolved, member_path):
            raise RuntimeError(f"不安全的 tar 成员路径: {member.name}")
    tar.extractall(dest_dir)


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    dest_dir_resolved = dest_dir.resolve()
    for name in zf.namelist():
        member_path = dest_dir / name
        if not _is_within(dest_dir_resolved, member_path):
            raise RuntimeError(f"不安全的 zip 成员路径: {name}")
    zf.extractall(dest_dir)


def extract_source_archive(archive_path: Path, extract_dir: Path) -> None:
    """
    Extract downloaded source archive into extract_dir.
    Supports tar/tar.gz/zip and plain single-tex fallback.
    """
    extract_dir.mkdir(parents=True, exist_ok=True)

    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path, "r:*") as tar:
            _safe_extract_tar(tar, extract_dir)
        return

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path, "r") as zf:
            _safe_extract_zip(zf, extract_dir)
        return

    # Fallback: some sources can be plain tex text.
    raw = archive_path.read_bytes()
    text = raw.decode("utf-8", errors="ignore")
    if "\\documentclass" in text:
        (extract_dir / "main.tex").write_text(text, encoding="utf-8")
        return

    raise RuntimeError("源码包格式不受支持（非 tar/zip/plain tex）。")
