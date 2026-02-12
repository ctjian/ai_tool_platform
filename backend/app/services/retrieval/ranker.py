"""Embedding-based ranker using cosine similarity."""

from __future__ import annotations

from typing import Dict, List
import numpy as np


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def rank_chunks(
    query_embedding: List[float],
    chunks: List[Dict],
    chunk_embedding_map: Dict[str, List[float]],
    top_k: int = 8,
) -> List[Dict]:
    """Return top-k chunks with score metadata."""
    scored = []
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        if not chunk_id:
            continue
        emb = chunk_embedding_map.get(chunk_id)
        if not emb:
            continue
        score = _cosine_similarity(query_embedding, emb)
        scored.append({"chunk": chunk, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[: max(1, int(top_k))]
