"""Parse arXiv IDs from user input.

Review note:
- 支持整条消息扫描并提取多篇 arXiv 引用（URL/裸ID）。
- 支持会话 active paper 状态回放：可由已存 paper_id/canonical_id 重建目标对象。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional


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
    position: str  # "message"


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


def extract_arxiv_targets(
    message: str,
    max_refs: Optional[int] = None,
) -> List[ArxivTarget]:
    """Parse zero-to-many arXiv references from the whole input message."""
    text = message or ""
    if not text.strip():
        return []

    candidates = _extract_candidates(text, "message")

    unique: dict[str, ArxivTarget] = {}
    for item in candidates:
        unique[item.paper_id] = item

    found = list(unique.values())
    if not found:
        return []

    if max_refs and max_refs > 0:
        return found[: int(max_refs)]
    return found


def build_target_from_ids(
    paper_id: str,
    canonical_id: Optional[str] = None,
    source_fragment: str = "conversation_active",
    position: str = "conversation_active",
) -> Optional[ArxivTarget]:
    """Build target from persisted paper identifiers in conversation extra."""
    normalized = normalize_arxiv_id(paper_id)
    if not normalized:
        return None
    normalized_paper_id, normalized_canonical_id = normalized
    canonical = (canonical_id or normalized_canonical_id).strip() or normalized_canonical_id
    return ArxivTarget(
        paper_id=normalized_paper_id,
        canonical_id=canonical,
        safe_id=safe_id_from_canonical(canonical),
        source_fragment=source_fragment,
        position=position,
    )


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


def remove_detected_arxiv_references(message: str, targets: List[ArxivTarget]) -> str:
    """Remove all detected arXiv references from a message."""
    out = message or ""
    for target in targets or []:
        out = remove_detected_arxiv_reference(out, target)
    return out
