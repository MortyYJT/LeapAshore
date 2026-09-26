from collections.abc import Sequence
import math
import os
from urllib.parse import urlparse

import httpx


class EmbeddingProviderError(RuntimeError):
    """Safe-to-display upstream embedding failure without response content or secrets."""


class EmbeddingProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sync_transport: httpx.BaseTransport | None = None,
    ):
        if not api_key.strip():
            raise ValueError("embedding API key is required")
        if not model.strip() or dimensions < 1:
            raise ValueError("embedding model and positive dimensions are required")
        self._url = base_url.rstrip("/") + "/embeddings"
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport
        self._sync_transport = sync_transport
        self._base_url = base_url.rstrip("/")

    async def embed_query(self, query: str, *, cloud_processing_consented: bool = False) -> list[float]:
        host = (urlparse(self._base_url).hostname or "").lower()
        local_hosts = {"localhost", "127.0.0.1", "::1", "embedding", "embedding-service", "embedding-agent", "milvus-embedding"}
        if host not in local_hosts and not host.endswith((".internal", ".local")) and not cloud_processing_consented:
            raise EmbeddingProviderError("remote query embedding requires explicit cloud-processing consent")
        vectors = await self.embed_documents([query])
        return vectors[0]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding input must contain non-empty text")
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": list(texts)},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise EmbeddingProviderError(f"embedding provider unavailable{suffix}") from None

        return self._parse_vectors(payload, len(texts))

    def embed_query_sync(self, query: str, *, cloud_processing_consented: bool = False) -> list[float]:
        host = (urlparse(self._base_url).hostname or "").lower()
        local_hosts = {"localhost", "127.0.0.1", "::1", "embedding", "embedding-service", "embedding-agent", "milvus-embedding"}
        if host not in local_hosts and not host.endswith((".internal", ".local")) and not cloud_processing_consented:
            raise EmbeddingProviderError("remote query embedding requires explicit cloud-processing consent")
        return self.embed_documents_sync([query])[0]

    def embed_documents_sync(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding input must contain non-empty text")
        try:
            with httpx.Client(timeout=self._timeout, transport=self._sync_transport) as client:
                response = client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": list(texts)},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise EmbeddingProviderError(f"embedding provider unavailable{suffix}") from None
        return self._parse_vectors(payload, len(texts))

    def _parse_vectors(self, payload: object, expected_count: int) -> list[list[float]]:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != expected_count:
            raise EmbeddingProviderError("embedding provider returned an invalid result count")
        vectors: list[list[float]] = []
        for item in data:
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list) or len(vector) != self._dimensions:
                raise EmbeddingProviderError("embedding dimension mismatch")
            if any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in vector):
                raise EmbeddingProviderError("embedding provider returned invalid values")
            vectors.append([float(value) for value in vector])
        return vectors


def embedding_provider_from_env() -> EmbeddingProvider:
    base_url = os.getenv("EMBEDDING_BASE_URL", "").strip()
    api_key = os.getenv("EMBEDDING_API_KEY", "")
    model = os.getenv("EMBEDDING_MODEL", "bge-m3")
    dimensions = int(os.getenv("MILVUS_EMBEDDING_DIMENSIONS", "1024"))
    if not base_url:
        raise ValueError("EMBEDDING_BASE_URL is required")
    return EmbeddingProvider(base_url, api_key, model, dimensions)
