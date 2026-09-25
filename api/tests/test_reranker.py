import httpx
import pytest

from app.services.reranker import CrossEncoderReranker, RerankerError, reranker_from_env


def test_cross_encoder_sends_only_query_and_bounded_candidate_texts() -> None:
    received = []

    def handler(request):
        received.append(request)
        return httpx.Response(200, json=[{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}])

    reranker = CrossEncoderReranker("http://reranker-agent", transport=httpx.MockTransport(handler))
    order = reranker("official requirement", [
        {"chunk_id": "a", "text": "official fact A"},
        {"chunk_id": "b", "text": "official fact B"},
    ])
    assert order == ["b", "a"]
    assert received[0].url.path == "/rerank"


def test_cross_encoder_requires_internal_host_and_hides_upstream_body() -> None:
    with pytest.raises(ValueError, match="internal"):
        CrossEncoderReranker("https://public.example/rerank")
    reranker = CrossEncoderReranker("http://reranker-agent", transport=httpx.MockTransport(lambda _req: httpx.Response(503, text="private detail")))
    with pytest.raises(RerankerError) as error:
        reranker("query", [{"chunk_id": "a", "text": "public fact"}])
    assert "private detail" not in str(error.value)


def test_reranker_factory_rejects_remote_endpoint_without_internal_host(monkeypatch) -> None:
    monkeypatch.setenv("RERANKER_BASE_URL", "https://public.example")
    with pytest.raises(ValueError, match="internal"):
        reranker_from_env()
