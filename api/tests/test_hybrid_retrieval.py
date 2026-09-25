import pytest

from app.services.hybrid_retrieval import filter_current_sources, fuse_rankings, rerank_candidates, retrieve_hybrid


def hit(chunk_id: str, text: str) -> dict:
    version = "v2" if chunk_id.startswith("fresh") else "v1"
    return {"id": chunk_id, "entity": {"chunk_id": chunk_id, "text": text, "program_slug": "uq", "source_version_id": version}}


def test_rrf_combines_channel_ranks_and_merges_duplicate_chunks() -> None:
    dense = [hit("a", "A"), hit("b", "B")]
    lexical = [hit("b", "B"), hit("c", "C")]
    fused = fuse_rankings(dense, lexical, k=60)
    assert [item["chunk_id"] for item in fused] == ["b", "a", "c"]
    assert fused[0]["rrf_score"] == pytest.approx(1 / 62 + 1 / 61)
    assert len({item["chunk_id"] for item in fused}) == 3


def test_rrf_does_not_mutate_source_hits() -> None:
    dense = [hit("a", "A")]
    original = {**dense[0]["entity"]}
    fuse_rankings(dense, [], k=60)
    assert dense[0]["entity"] == original


def test_reranker_is_bounded_and_cannot_add_or_drop_citations() -> None:
    candidates = fuse_rankings([hit(str(i), f"text {i}") for i in range(5)], [], k=60)
    seen = []

    def rerank(_query, bounded):
        seen.extend(item["chunk_id"] for item in bounded)
        return list(reversed(seen))

    reordered = rerank_candidates("query", candidates, rerank, max_candidates=3)
    assert len(seen) == 3
    assert {item["chunk_id"] for item in reordered} == {item["chunk_id"] for item in candidates}
    assert [item["chunk_id"] for item in reordered][-2:] == ["3", "4"]


def test_invalid_reranker_output_keeps_rrf_order() -> None:
    candidates = fuse_rankings([hit("a", "A"), hit("b", "B")], [], k=60)
    reordered = rerank_candidates("query", candidates, lambda _q, _items: ["foreign"], max_candidates=5)
    assert [item["chunk_id"] for item in reordered] == ["a", "b"]


def test_unpublished_or_superseded_source_versions_are_removed_before_return() -> None:
    candidates = [
        {"chunk_id": "fresh", "program_slug": "uq", "source_version_id": "v2"},
        {"chunk_id": "stale", "program_slug": "uq", "source_version_id": "v1"},
    ]
    current = filter_current_sources(candidates, lambda _program, version: version == "v2")
    assert [item["chunk_id"] for item in current] == ["fresh"]


def test_hybrid_path_filters_freshness_before_reranking() -> None:
    class Index:
        def search_dense(self, _vector, **_kwargs):
            return [hit("stale", "old"), hit("fresh", "new"), hit("fresh-2", "newer")]

        def search_bm25(self, _query, **_kwargs):
            return [hit("fresh", "new"), hit("stale", "old"), hit("fresh-2", "newer")]

    reranked_input = []

    def reranker(_query, items):
        reranked_input.extend(item["chunk_id"] for item in items)
        return list(reversed(reranked_input))

    result = retrieve_hybrid(
        "official query", [0.1, 0.2], index=Index(),
        source_is_current=lambda _program, version: version == "v2",
        reranker=reranker,
    )
    assert reranked_input == ["fresh", "fresh-2"]
    assert [item["chunk_id"] for item in result] == ["fresh-2", "fresh"]
