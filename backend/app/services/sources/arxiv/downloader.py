"""Download arXiv PDFs."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple
import hashlib

import httpx


class ArxivDownloadError(RuntimeError):
    """Raised when a paper PDF cannot be downloaded."""


def _candidate_urls(paper_id: str, canonical_id: str) -> list[str]:
    urls = [f"https://arxiv.org/pdf/{paper_id}.pdf"]
    if canonical_id != paper_id:
        urls.append(f"https://arxiv.org/pdf/{canonical_id}.pdf")
    return urls


def download_arxiv_pdf(
    paper_id: str,
    canonical_id: str,
    output_pdf: Path,
    timeout_sec: int = 30,
) -> Tuple[str, int, str]:
    """
    Download PDF and return (url, size_bytes, sha256).
    """
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    last_error = "unknown"

    with httpx.Client(follow_redirects=True, timeout=timeout_sec) as client:
        for url in _candidate_urls(paper_id, canonical_id):
            try:
                response = client.get(url)
                if response.status_code != 200:
                    last_error = f"{response.status_code} {url}"
                    continue

                data = response.content
                if not data.startswith(b"%PDF"):
                    last_error = f"non-pdf-content {url}"
                    continue

                output_pdf.write_bytes(data)
                size = output_pdf.stat().st_size
                sha256 = hashlib.sha256(data).hexdigest()
                return url, size, sha256
            except Exception as exc:  # pragma: no cover - network exceptions
                last_error = str(exc)

    raise ArxivDownloadError(f"下载 arXiv PDF 失败: {last_error}")

