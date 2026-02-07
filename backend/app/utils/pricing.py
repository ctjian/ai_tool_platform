"""计费计算工具"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings


@lru_cache(maxsize=1)
def _load_pricing_data() -> Dict[str, Any]:
    path = Path(settings.PRICING_FILE)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _find_model_entry(model_name: str) -> Optional[Dict[str, Any]]:
    data = _load_pricing_data().get("data", [])
    for item in data:
        if item.get("model_name") == model_name:
            return item
    if model_name.startswith("new-"):
        stripped = model_name[4:]
        for item in data:
            if item.get("model_name") == stripped:
                return item
    return None


def compute_text_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Optional[Dict[str, Any]]:
    entry = _find_model_entry(model_name)
    base_price = settings.PRICE_INPUT_PER_1M
    group_ratio = settings.PRICE_GROUP_RATIO
    model_ratio = float(entry.get("model_ratio", 1)) if entry else 1.0
    completion_ratio = float(entry.get("completion_ratio", 1)) if entry else 1.0

    if base_price <= 0:
        return None

    prompt_cost = (prompt_tokens / 1_000_000) * base_price * model_ratio
    completion_cost = (completion_tokens / 1_000_000) * base_price * model_ratio * completion_ratio
    total_cost = (prompt_cost + completion_cost) * group_ratio

    return {
        "currency": settings.PRICE_CURRENCY,
        "model": model_name,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "base_price_per_1m": base_price,
        "model_ratio": model_ratio,
        "completion_ratio": completion_ratio,
        "group_ratio": group_ratio,
        "prompt_cost": prompt_cost,
        "completion_cost": completion_cost,
        "total_cost": total_cost,
    }
