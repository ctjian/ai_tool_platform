"""SiliconFlow embedding client."""

from __future__ import annotations

from typing import Iterable, List

import httpx


class EmbeddingConfigError(ValueError):
    """Raised when embedding configuration is invalid."""


class EmbeddingServiceError(RuntimeError):
    """Raised when embedding service request fails."""


class EmbeddingClient:
    """Simple sync client for embedding generation."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_sec: int = 60,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout_sec = int(timeout_sec)
        if not self.base_url:
            raise EmbeddingConfigError("EMBEDDING_BASE_URL 未配置。")
        if not self.api_key:
            raise EmbeddingConfigError("EMBEDDING_API_KEY 未配置。")
        if not self.model:
            raise EmbeddingConfigError("EMBEDDING_MODEL 未配置。")

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        normalized = [str(t or "").strip() for t in texts]
        payload = {
            "model": self.model,
            "input": normalized if len(normalized) > 1 else normalized[0],
            "encoding_format": "float",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/embeddings"

        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise EmbeddingServiceError(f"Embedding 请求失败: {exc}") from exc

        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise EmbeddingServiceError(
                f"Embedding 服务返回错误: status={resp.status_code}, body={detail}"
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise EmbeddingServiceError("Embedding 返回不是合法 JSON。") from exc

        data = body.get("data")
        if not isinstance(data, list):
            raise EmbeddingServiceError("Embedding 返回缺少 data 列表。")

        # 按 index 排序，保证与输入顺序一致。
        ordered = sorted(
            (item for item in data if isinstance(item, dict)),
            key=lambda x: int(x.get("index", 0)),
        )
        vectors: List[List[float]] = []
        for item in ordered:
            vec = item.get("embedding")
            if not isinstance(vec, list) or not vec:
                raise EmbeddingServiceError("Embedding 向量为空或格式错误。")
            vectors.append([float(v) for v in vec])

        if len(vectors) != len(normalized):
            raise EmbeddingServiceError(
                f"Embedding 数量不匹配: expected={len(normalized)}, got={len(vectors)}"
            )
        return vectors

    def embed_texts_batched(self, texts: List[str], batch_size: int = 16) -> List[List[float]]:
        if not texts:
            return []
        safe_batch = max(1, int(batch_size))
        all_vectors: List[List[float]] = []
        for batch in _chunked(texts, safe_batch):
            all_vectors.extend(self.embed_texts(batch))
        return all_vectors


def _chunked(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
