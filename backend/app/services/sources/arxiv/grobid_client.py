"""Call GROBID service for PDF parsing."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Dict, List

import httpx


class GrobidParseError(RuntimeError):
    """Raised when GROBID parsing fails."""


_ROUND_ROBIN_LOCK = Lock()
_ROUND_ROBIN_INDEX = 0


def _normalize_service_urls(service_urls: List[str]) -> List[str]:
    urls: List[str] = []
    seen = set()
    for raw in service_urls or []:
        url = str(raw or "").strip().rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _build_round_robin_order(urls: List[str]) -> List[str]:
    global _ROUND_ROBIN_INDEX
    if len(urls) <= 1:
        return list(urls)
    with _ROUND_ROBIN_LOCK:
        start = _ROUND_ROBIN_INDEX % len(urls)
        _ROUND_ROBIN_INDEX += 1
    return urls[start:] + urls[:start]


def _request_parse_once(
    *,
    pdf_path: Path,
    service_url: str,
    timeout_sec: int = 120,
) -> str:
    endpoint = f"{service_url}/api/processFulltextDocument"
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
        raise GrobidParseError(f"HTTP {response.status_code}")

    body = response.text or ""
    if "<TEI" not in body:
        raise GrobidParseError("返回内容不是有效 TEI XML")
    return body


def parse_pdf_to_tei(
    pdf_path: Path,
    tei_path: Path,
    service_urls: List[str],
    timeout_sec: int = 120,
) -> Dict[str, str]:
    """
    Parse local PDF via GROBID and write TEI XML to `tei_path`.

    Returns parse meta:
    {
      "service_url": "...",
      "endpoint": "...",
      "attempt": "1"
    }
    """
    urls = _normalize_service_urls(service_urls)
    if not urls:
        raise GrobidParseError("未配置 GROBID_URLS")

    ordered_urls = _build_round_robin_order(urls)
    tei_path.parent.mkdir(parents=True, exist_ok=True)
    errors: List[str] = []

    for idx, base in enumerate(ordered_urls):
        endpoint = f"{base}/api/processFulltextDocument"
        try:
            body = _request_parse_once(
                pdf_path=pdf_path,
                service_url=base,
                timeout_sec=timeout_sec,
            )
            tei_path.write_text(body, encoding="utf-8")
            return {
                "service_url": base,
                "endpoint": endpoint,
                "attempt": str(idx + 1),
            }
        except Exception as exc:
            errors.append(f"{base}: {exc}")
            continue

    summary = " | ".join(errors[:3])
    if len(errors) > 3:
        summary = f"{summary} | ... total={len(errors)}"
    raise GrobidParseError(f"GROBID 解析失败，已回退所有节点。{summary}")
