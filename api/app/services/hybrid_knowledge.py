from collections.abc import Sequence
from datetime import UTC, datetime
import os
from typing import Any

from ..models import KnowledgeEvidence, KnowledgeSearchRequest, KnowledgeSearchResponse, ProgramSourceVersion, SourceCitation
from ..program_data import PROGRAMS
from .embedding_provider import EmbeddingProvider
from .hybrid_retrieval import retrieve_hybrid
from .knowledge_chunks import PublishedProgramSnapshot, build_published_chunks
from .milvus_index import MilvusIndex, milvus_index_from_env
from .reranker import CrossEncoderReranker, reranker_from_env


HYBRID_RETRIEVAL_VERSION = "official-knowledge-hybrid-rrf-v1"


def rebuild_published_index(
    source_versions: Sequence[ProgramSourceVersion],
    *,
    index: MilvusIndex,
    embedder: EmbeddingProvider,
) -> int:
    """Rebuild current published facts only; drafts and invalid hashes produce no chunks."""
    snapshots = [
        PublishedProgramSnapshot(
            program=version.program,
            source_version_id=version.version_id,
            content_hash=version.content_hash,
            status=version.status,
        )
        for version in source_versions
        if version.status == "published"
    ]
    chunks = build_published_chunks(snapshots, embedding_model_version=embedder._model)
    index.ensure_collection()
    for version in source_versions:
        if version.status != "published":
            index.delete_source_version(version.version_id)
    if not chunks:
        return 0
    vectors = embedder.embed_documents_sync([chunk.content for chunk in chunks])
    return index.upsert(chunks, vectors)


def retrieve_hybrid_knowledge(
    request: KnowledgeSearchRequest,
    published_versions: Sequence[ProgramSourceVersion],
    *,
    index: Any,
    embedder: Any,
    reranker: Any = None,
    cloud_processing_consented: bool = False,
) -> KnowledgeSearchResponse:
    current_versions = {
        item.program_slug: item.version_id
        for item in published_versions if item.status == "published"
    }
    query_vector = embedder.embed_query_sync(
        request.query, cloud_processing_consented=cloud_processing_consented,
    )
    inferred_programs = request.program_slugs or _program_filter(request.query)
    candidates = retrieve_hybrid(
        request.query,
        query_vector,
        index=index,
        source_is_current=lambda slug, version: current_versions.get(slug) == version,
        program_slugs=inferred_programs,
        degree_level=request.target_degree_level,
        field=request.target_field,
        reranker=reranker,
        top_k=request.top_k,
    )
    programs = {program.slug: program for program in PROGRAMS}
    hits: list[KnowledgeEvidence] = []
    for rank, candidate in enumerate(candidates, start=1):
        program = programs.get(str(candidate.get("program_slug", "")))
        if not program:
            continue
        version_id = str(candidate.get("source_version_id", ""))
        if not version_id or current_versions.get(program.slug) != version_id:
            continue
        try:
            rrf_score = float(candidate.get("rrf_score", 0.0))
        except (TypeError, ValueError):
            continue
        # Map bounded reciprocal-rank evidence to the existing score scale. This is
        # a ranking feature, not a probability; threshold quality is reported by Eval.
        relevance = min(10.0, max(0.0, rrf_score * 300.0))
        hits.append(KnowledgeEvidence(
            chunk_id=str(candidate["chunk_id"]),
            program_slug=program.slug,
            university=program.university,
            program_name=program.name,
            section=str(candidate.get("section", "项目概览")),
            content=str(candidate.get("text", "")),
            relevance_score=relevance,
            source=SourceCitation(
                id=str(candidate.get("source_id", "")),
                title=str(candidate.get("source_title", "")),
                url=str(candidate.get("source_url", "")),
                excerpt=str(candidate.get("text", "")),
                verified_at=str(candidate.get("verification_date", "")),
                version_id=version_id,
                content_hash=str(candidate.get("source_content_hash", "")),
            ),
        ))
    return KnowledgeSearchResponse(
        query=request.query,
        retrieval_version=HYBRID_RETRIEVAL_VERSION,
        generated_at=datetime.now(UTC),
        hits=hits,
        coverage_notice=(
            "仅使用当前发布的官方来源；结果经 BM25 与向量召回融合，并过滤失效版本。"
            if hits else "当前已发布官方知识索引没有可引用的匹配内容。"
        ),
    )


def configured_hybrid_retrieval(
    request: KnowledgeSearchRequest,
    published_versions: Sequence[ProgramSourceVersion],
    *,
    cloud_processing_consented: bool,
) -> KnowledgeSearchResponse:
    if os.getenv("HYBRID_RAG_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("hybrid retrieval feature flag is disabled")
    from .embedding_provider import embedding_provider_from_env

    index = milvus_index_from_env()
    embedder = embedding_provider_from_env()
    reranker: CrossEncoderReranker | None = None
    if os.getenv("RERANKER_BASE_URL", "").strip():
        reranker = reranker_from_env()
    return retrieve_hybrid_knowledge(
        request,
        published_versions,
        index=index,
        embedder=embedder,
        reranker=reranker,
        cloud_processing_consented=cloud_processing_consented,
    )


def rebuild_configured_published_index(source_versions: Sequence[ProgramSourceVersion]) -> int:
    from .embedding_provider import embedding_provider_from_env

    index = milvus_index_from_env()
    embedder = embedding_provider_from_env()
    return rebuild_published_index(source_versions, index=index, embedder=embedder)


def _program_filter(query: str) -> list[str]:
    from .knowledge_rag import infer_program_slugs

    return infer_program_slugs(query)
