import asyncio

import httpx
import pytest

from app.services.embedding_provider import EmbeddingProvider, EmbeddingProviderError, embedding_provider_from_env


def test_embedding_provider_uses_configured_endpoint_and_checks_dimensions() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}], "model": "bge-m3-test"})

    async def exercise() -> None:
        provider = EmbeddingProvider("https://embed.example/v1", "local-secret", "bge-m3-test", 2,
                                     transport=httpx.MockTransport(handler))
        vectors = await provider.embed_documents(["approved public fact"])
        assert vectors == [[0.1, 0.2]]

    asyncio.run(exercise())
    assert requests[0].url.path == "/v1/embeddings"
    assert requests[0].headers["authorization"] == "Bearer local-secret"


def test_embedding_provider_fails_closed_on_wrong_dimension() -> None:
    async def exercise() -> None:
        provider = EmbeddingProvider("https://embed.example", "key", "model", 3,
                                     transport=httpx.MockTransport(lambda _req: httpx.Response(200, json={"data": [{"embedding": [1, 2]}]})))
        with pytest.raises(EmbeddingProviderError, match="dimension"):
            await provider.embed_documents(["fact"])

    asyncio.run(exercise())


def test_embedding_provider_rejects_empty_key_and_hides_upstream_body() -> None:
    with pytest.raises(ValueError, match="API key"):
        EmbeddingProvider("https://embed.example", "", "model", 2)

    async def exercise() -> None:
        provider = EmbeddingProvider("https://embed.example", "secret", "model", 2,
                                     transport=httpx.MockTransport(lambda _req: httpx.Response(429, text="private upstream detail")))
        with pytest.raises(EmbeddingProviderError) as error:
            await provider.embed_documents(["fact"])
        assert "private upstream detail" not in str(error.value)
        assert "secret" not in str(error.value)

    asyncio.run(exercise())


def test_remote_query_embedding_requires_explicit_consent() -> None:
    async def exercise() -> None:
        provider = EmbeddingProvider(
            "https://embed.example/v1", "key", "model", 2,
            transport=httpx.MockTransport(lambda _req: httpx.Response(200, json={"data": [{"embedding": [0.2, 0.3]}]})),
        )
        with pytest.raises(EmbeddingProviderError, match="consent"):
            await provider.embed_query("applicant asks something")
        assert await provider.embed_query("approved query", cloud_processing_consented=True) == [0.2, 0.3]

    asyncio.run(exercise())


def test_embedding_provider_factory_uses_private_config_names(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://embedding-agent/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "local-only")
    monkeypatch.setenv("EMBEDDING_MODEL", "bge-m3")
    monkeypatch.setenv("MILVUS_EMBEDDING_DIMENSIONS", "1024")
    provider = embedding_provider_from_env()
    assert provider._url == "http://embedding-agent/v1/embeddings"
