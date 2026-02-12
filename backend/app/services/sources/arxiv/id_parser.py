"""Parse arXiv IDs from user input."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional


WINDOW_CHARS_DEFAULT = 100


class ArxivParseError(ValueError):
    """Base class for arXiv parse errors."""


class MultipleArxivReferencesError(ArxivParseError):
    """Raised when more than one unique arXiv reference is found."""


@dataclass(frozen=True)
class ArxivTarget:
    """Normalized arXiv target extracted from user input."""

    paper_id: str
    canonical_id: str
    safe_id: str
    source_fragment: str
    position: str  # "prefix" | "suffix"


_URL_ID_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/"
    r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z\-]+/\d{7})(?:v\d+)?)"
    r"(?:\.pdf)?",
    re.IGNORECASE,
)
_BARE_ID_PATTERN = re.compile(
    r"\b(?P<id>(?:\d{4}\.\d{4,5}|[a-z\-]+/\d{7})(?:v\d+)?)\b",
    re.IGNORECASE,
)
_TRAILING_PUNCT = ".,;:!?)]}\"'`>"


def normalize_arxiv_id(raw: str) -> Optional[tuple[str, str]]:
    """Return (paper_id_with_version, canonical_id_without_version) or None."""
    value = (raw or "").strip().strip(_TRAILING_PUNCT)
    if not value:
        return None

    value = re.sub(r"^(?:arxiv:)", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\.pdf$", "", value, flags=re.IGNORECASE)

    m_new = re.fullmatch(r"(\d{4}\.\d{4,5})(v\d+)?", value, flags=re.IGNORECASE)
    if m_new:
        canonical = m_new.group(1)
        version = m_new.group(2) or ""
        return canonical + version, canonical

    m_old = re.fullmatch(r"([a-z\-]+/\d{7})(v\d+)?", value, flags=re.IGNORECASE)
    if m_old:
        canonical = m_old.group(1).lower()
        version = (m_old.group(2) or "").lower()
        return canonical + version, canonical

    return None


def safe_id_from_canonical(canonical_id: str) -> str:
    """Convert canonical ID to filesystem-safe ID."""
    return canonical_id.replace("/", "_")


def _extract_candidates(text: str, position: str) -> List[ArxivTarget]:
    candidates: List[ArxivTarget] = []
    seen: set[str] = set()

    def add_candidate(raw_id: str, source_fragment: Optional[str] = None):
        normalized = normalize_arxiv_id(raw_id)
        if not normalized:
            return
        paper_id, canonical_id = normalized
        if paper_id in seen:
            return
        seen.add(paper_id)
        candidates.append(
            ArxivTarget(
                paper_id=paper_id,
                canonical_id=canonical_id,
                safe_id=safe_id_from_canonical(canonical_id),
                source_fragment=source_fragment or raw_id,
                position=position,
            )
        )

    for m in _URL_ID_PATTERN.finditer(text):
        add_candidate(m.group("id"), source_fragment=m.group(0))

    for m in _BARE_ID_PATTERN.finditer(text):
        add_candidate(m.group("id"), source_fragment=m.group(0))

    return candidates


def extract_single_arxiv_target(
    message: str,
    window_chars: int = WINDOW_CHARS_DEFAULT,
) -> Optional[ArxivTarget]:
    """
    Parse at most one arXiv reference from the first/last window of input.

    This intentionally only inspects the first `window_chars` and last
    `window_chars` characters as requested by product requirements.
    """
    text = message or ""
    if not text.strip():
        return None

    window = max(1, int(window_chars))
    prefix = text[:window]
    suffix = text[-window:] if len(text) > window else text

    candidates = _extract_candidates(prefix, "prefix")
    candidates.extend(_extract_candidates(suffix, "suffix"))

    unique: dict[str, ArxivTarget] = {}
    for item in candidates:
        unique[item.paper_id] = item

    found = list(unique.values())
    if not found:
        return None
    if len(found) > 1:
        raise MultipleArxivReferencesError("一次只支持解析一篇 arXiv 论文，请只保留一个链接或ID。")
    return found[0]


def remove_detected_arxiv_reference(message: str, target: ArxivTarget) -> str:
    """Remove the detected arXiv reference from the user message."""
    text = message or ""
    if not text:
        return text

    # Remove URL forms first to avoid leaving dangling "https://arxiv.org/abs/".
    patterns = [
        re.escape(f"https://arxiv.org/abs/{target.paper_id}"),
        re.escape(f"http://arxiv.org/abs/{target.paper_id}"),
        re.escape(f"www.arxiv.org/abs/{target.paper_id}"),
        re.escape(f"arxiv.org/abs/{target.paper_id}"),
        re.escape(f"https://arxiv.org/abs/{target.canonical_id}"),
        re.escape(f"http://arxiv.org/abs/{target.canonical_id}"),
        re.escape(f"www.arxiv.org/abs/{target.canonical_id}"),
        re.escape(f"arxiv.org/abs/{target.canonical_id}"),
        re.escape(f"https://arxiv.org/pdf/{target.paper_id}.pdf"),
        re.escape(f"http://arxiv.org/pdf/{target.paper_id}.pdf"),
        re.escape(f"www.arxiv.org/pdf/{target.paper_id}.pdf"),
        re.escape(f"arxiv.org/pdf/{target.paper_id}.pdf"),
        re.escape(f"https://arxiv.org/pdf/{target.canonical_id}.pdf"),
        re.escape(f"http://arxiv.org/pdf/{target.canonical_id}.pdf"),
        re.escape(f"www.arxiv.org/pdf/{target.canonical_id}.pdf"),
        re.escape(f"arxiv.org/pdf/{target.canonical_id}.pdf"),
        re.escape(target.source_fragment),
        re.escape(target.paper_id),
        re.escape(target.canonical_id),
    ]
    out = text
    for p in patterns:
        out = re.sub(p, " ", out, flags=re.IGNORECASE)
    out = re.sub(
        r"(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/",
        " ",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\s+", " ", out).strip()
    return out
