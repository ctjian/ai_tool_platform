"""Conversation paper state helpers.

Review note:
- 所有会话级论文状态写入 conversations.extra(JSON)。
- `registry` 记录会话涉及过的论文；`active_ids` 决定当前检索参与的论文集合。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
import json


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_state() -> Dict[str, Any]:
    return {
        "v": 1,
        "papers": {
            "active_ids": [],
            "registry": {},
        },
    }


def parse_conversation_extra(raw: Any) -> Dict[str, Any]:
    """Parse conversation.extra JSON into normalized dict state."""
    if isinstance(raw, dict):
        payload = deepcopy(raw)
    elif isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}
    return normalize_state(payload)


def serialize_conversation_extra(extra: Dict[str, Any]) -> str:
    """Serialize normalized conversation extra dict to JSON string."""
    return json.dumps(normalize_state(extra), ensure_ascii=False)


def normalize_state(extra: Dict[str, Any]) -> Dict[str, Any]:
    state = _base_state()
    if not isinstance(extra, dict):
        return state

    papers = extra.get("papers")
    if isinstance(papers, dict):
        registry = papers.get("registry")
        if isinstance(registry, dict):
            normalized_registry: Dict[str, Dict[str, Any]] = {}
            for canonical_id, item in registry.items():
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("canonical_id") or canonical_id or "").strip()
                if not cid:
                    continue
                normalized_registry[cid] = {
                    "canonical_id": cid,
                    "paper_id": str(item.get("paper_id") or cid).strip(),
                    "filename": str(item.get("filename") or f"{cid}.pdf").strip(),
                    "pdf_url": str(item.get("pdf_url") or f"/papers/{cid}/{cid}.pdf").strip(),
                    "title": str(item.get("title") or "").strip(),
                    "safe_id": str(item.get("safe_id") or cid).strip(),
                    "last_seen_at": str(item.get("last_seen_at") or "").strip() or _now_iso(),
                }
            state["papers"]["registry"] = normalized_registry

        active_ids = papers.get("active_ids")
        if isinstance(active_ids, list):
            cleaned: List[str] = []
            seen: set[str] = set()
            for item in active_ids:
                cid = str(item or "").strip()
                if not cid or cid in seen:
                    continue
                if cid not in state["papers"]["registry"]:
                    continue
                seen.add(cid)
                cleaned.append(cid)
            state["papers"]["active_ids"] = cleaned

    return state


def upsert_registry_entries(
    extra: Dict[str, Any],
    entries: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    state = normalize_state(extra)
    registry = state["papers"]["registry"]
    now = _now_iso()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        canonical_id = str(entry.get("canonical_id") or "").strip()
        if not canonical_id:
            continue
        existing = registry.get(canonical_id, {})
        merged = {
            "canonical_id": canonical_id,
            "paper_id": str(entry.get("paper_id") or existing.get("paper_id") or canonical_id).strip(),
            "filename": str(entry.get("filename") or existing.get("filename") or f"{canonical_id}.pdf").strip(),
            "pdf_url": str(entry.get("pdf_url") or existing.get("pdf_url") or f"/papers/{canonical_id}/{canonical_id}.pdf").strip(),
            "title": str(entry.get("title") or existing.get("title") or "").strip(),
            "safe_id": str(entry.get("safe_id") or existing.get("safe_id") or canonical_id).strip(),
            "last_seen_at": now,
        }
        registry[canonical_id] = merged
    return state


def activate_papers_in_conversation(
    extra: Dict[str, Any],
    canonical_ids: Iterable[str],
    max_active: Optional[int] = None,
) -> Dict[str, Any]:
    state = normalize_state(extra)
    active_ids: List[str] = list(state["papers"]["active_ids"])
    registry = state["papers"]["registry"]
    limit = max_active if max_active and max_active > 0 else None

    for canonical_id in canonical_ids:
        cid = str(canonical_id or "").strip()
        if not cid:
            continue
        if cid not in registry:
            continue
        if cid in active_ids:
            continue
        if limit is not None and len(active_ids) >= limit:
            break
        active_ids.append(cid)

    state["papers"]["active_ids"] = active_ids
    return state


def deactivate_paper_in_conversation(
    extra: Dict[str, Any],
    canonical_id: str,
) -> Dict[str, Any]:
    state = normalize_state(extra)
    cid = str(canonical_id or "").strip()
    if not cid:
        return state
    state["papers"]["active_ids"] = [x for x in state["papers"]["active_ids"] if x != cid]
    return state


def list_papers_from_extra(extra: Dict[str, Any]) -> Dict[str, Any]:
    state = normalize_state(extra)
    active_set = set(state["papers"]["active_ids"])
    registry = state["papers"]["registry"]
    papers: List[Dict[str, Any]] = []
    for canonical_id, item in registry.items():
        papers.append(
            {
                "canonical_id": canonical_id,
                "paper_id": item.get("paper_id"),
                "filename": item.get("filename"),
                "pdf_url": item.get("pdf_url"),
                "title": item.get("title"),
                "safe_id": item.get("safe_id"),
                "last_seen_at": item.get("last_seen_at"),
                "is_active": canonical_id in active_set,
            }
        )

    # 保持稳定展示顺序：按最近出现时间排序，不因 active 开关变化而重排。
    papers.sort(
        key=lambda x: (
            x.get("last_seen_at") or "",
            x.get("canonical_id") or "",
        ),
        reverse=True,
    )
    return {
        "active_ids": list(state["papers"]["active_ids"]),
        "papers": papers,
    }


def get_active_registry_entries(extra: Dict[str, Any]) -> List[Dict[str, Any]]:
    state = normalize_state(extra)
    registry = state["papers"]["registry"]
    out: List[Dict[str, Any]] = []
    for canonical_id in state["papers"]["active_ids"]:
        item = registry.get(canonical_id)
        if item:
            out.append(deepcopy(item))
    return out
