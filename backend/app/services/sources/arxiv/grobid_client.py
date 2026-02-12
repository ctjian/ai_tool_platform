"""Call GROBID service for PDF parsing."""

from __future__ import annotations

from pathlib import Path

import httpx


class GrobidParseError(RuntimeError):
    """Raised when GROBID parsing fails."""


def _normalize_service_url(service_url: str) -> str:
    return (service_url or "").rstrip("/")


def parse_pdf_to_tei(
    pdf_path: Path,
    tei_path: Path,
    service_url: str,
    timeout_sec: int = 120,
) -> str:
    """
    Parse local PDF via GROBID and write TEI XML to `tei_path`.

    Returns the endpoint URL used.
    """
    base = _normalize_service_url(service_url)
    if not base:
        raise GrobidParseError("未配置 GROBID_URL")

    endpoint = f"{base}/api/processFulltextDocument"
    tei_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=timeout_sec) as client:
        with pdf_path.open("rb") as fp:
            response = client.post(
                endpoint,
                files={"input": (pdf_path.name, fp, "application/pdf")},
                data={
                    "consolidateHeader": "0",
                    "consolidateCitations": "0",
                    "segmentSentences": "1",
                },
                headers={"Accept": "application/xml"},
            )

    if response.status_code != 200:
        raise GrobidParseError(f"GROBID 解析失败: HTTP {response.status_code}")

    body = response.text or ""
    if "<TEI" not in body:
        raise GrobidParseError("GROBID 返回内容不是有效 TEI XML")

    tei_path.write_text(body, encoding="utf-8")
    return endpoint

