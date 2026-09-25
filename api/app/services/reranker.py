from collections.abc import Mapping, Sequence
import math
import os
from urllib.parse import urlparse

import httpx


class RerankerError(RuntimeError):
    """Safe cross-encoder error; never includes query or candidate text."""


class CrossEncoderReranker:
    def __init__(self, base_url: str, *, timeout_seconds: float = 3.0, transport: httpx.BaseTransport | None = None):
        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
        local_hosts = {"localhost", "127.0.0.1", "::1", "reranker-agent", "embedding-agent"}
        if host not in local_hosts and not host.endswith((".internal", ".local")):
            raise ValueError("cross-encoder must use an internal inference endpoint")
        self._url = base_url.rstrip("/") + "/rerank"
        self._timeout = timeout_seconds
        self._transport = transport

    def __call__(self, query: str, candidates: Sequence[Mapping[str, object]]) -> list[str]:
        candidate_ids = [str(item["chunk_id"]) for item in candidates]
        texts = [str(item.get("text", "")) for item in candidates]
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(self._url, json={"query": query, "texts": texts, "raw_scores": False})
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError):
            raise RerankerError("cross-encoder inference unavailable") from None
        if not isinstance(result, list) or len(result) != len(candidate_ids):
            raise RerankerError("cross-encoder returned invalid result count")
        indices = [item.get("index") for item in result if isinstance(item, dict)]
        if len(indices) != len(candidate_ids) or set(indices) != set(range(len(candidate_ids))):
            raise RerankerError("cross-encoder returned invalid candidate indices")
        scored = []
        for item in result:
            try:
                score = float(item.get("score"))
            except (TypeError, ValueError):
                raise RerankerError("cross-encoder returned an invalid score") from None
            if not math.isfinite(score):
                raise RerankerError("cross-encoder returned an invalid score")
            scored.append((item["index"], score))
        return [candidate_ids[index] for index, _score in sorted(scored, key=lambda pair: pair[1], reverse=True)]


def reranker_from_env() -> CrossEncoderReranker:
    base_url = os.getenv("RERANKER_BASE_URL", "").strip()
    if not base_url:
        raise ValueError("RERANKER_BASE_URL is required")
    timeout = max(0.1, min(float(os.getenv("RERANKER_TIMEOUT_SECONDS", "3")), 10.0))
    return CrossEncoderReranker(base_url, timeout_seconds=timeout)
