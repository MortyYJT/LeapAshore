from collections.abc import Callable, Sequence
from typing import Any


def _hit_fields(hit: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(hit, dict):
        hit = dict(hit)
    entity = hit.get("entity") if isinstance(hit.get("entity"), dict) else hit
    chunk_id = str(entity.get("chunk_id") or hit.get("id") or "")
    if not chunk_id:
        raise ValueError("retrieval hit has no chunk identifier")
    return chunk_id, dict(entity)


def fuse_rankings(
    dense_hits: Sequence[Any],
    bm25_hits: Sequence[Any],
    *,
    k: int = 60,
) -> list[dict[str, Any]]:
    if k < 1:
        raise ValueError("RRF k must be positive")
    fused: dict[str, dict[str, Any]] = {}
    for channel, ranking in (("dense_rank", dense_hits), ("bm25_rank", bm25_hits)):
        for rank, hit in enumerate(ranking, start=1):
            chunk_id, entity = _hit_fields(hit)
            candidate = fused.setdefault(chunk_id, {**entity, "chunk_id": chunk_id, "rrf_score": 0.0})
            candidate["rrf_score"] += 1.0 / (k + rank)
            candidate[channel] = rank
    return sorted(fused.values(), key=lambda item: (-item["rrf_score"], item["chunk_id"]))


def rerank_candidates(
    query: str,
    candidates: Sequence[dict[str, Any]],
    reranker: Callable[[str, Sequence[dict[str, Any]]], Sequence[str]] | None,
    *,
    max_candidates: int,
) -> list[dict[str, Any]]:
    baseline = [dict(candidate) for candidate in candidates]
    if reranker is None or max_candidates < 1 or len(baseline) < 2:
        return baseline
    bounded = baseline[:max_candidates]
    baseline_ids = [str(item["chunk_id"]) for item in bounded]
    try:
        proposed = list(reranker(query, bounded))
    except Exception:
        return baseline
    if len(proposed) != len(baseline_ids) or set(proposed) != set(baseline_ids):
        return baseline
    by_id = {str(item["chunk_id"]): item for item in bounded}
    return [by_id[str(chunk_id)] for chunk_id in proposed] + baseline[max_candidates:]


def filter_current_sources(
    candidates: Sequence[dict[str, Any]],
    is_current_source: Callable[[str, str], bool],
) -> list[dict[str, Any]]:
    current = []
    for item in candidates:
        version_id = str(item.get("source_version_id", ""))
        program_slug = str(item.get("program_slug", ""))
        if version_id and program_slug and is_current_source(program_slug, version_id):
            current.append(dict(item))
    return current


def retrieve_hybrid(
    query: str,
    query_embedding: Sequence[float],
    *,
    index: Any,
    source_is_current: Callable[[str, str], bool],
    program_slugs: Sequence[str] = (),
    section: str | None = None,
    degree_level: str | None = None,
    field: str | None = None,
    reranker: Callable[[str, Sequence[dict[str, Any]]], Sequence[str]] | None = None,
    candidate_limit: int = 30,
    rerank_limit: int = 10,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    if not query.strip() or min(candidate_limit, top_k) < 1:
        return []
    dense = index.search_dense(query_embedding, top_k=candidate_limit, program_slugs=program_slugs, section=section, degree_level=degree_level, field=field)
    bm25 = index.search_bm25(query, top_k=candidate_limit, program_slugs=program_slugs, section=section, degree_level=degree_level, field=field)
    candidates = filter_current_sources(fuse_rankings(dense, bm25), source_is_current)
    return rerank_candidates(query, candidates, reranker, max_candidates=min(rerank_limit, candidate_limit))[:top_k]
