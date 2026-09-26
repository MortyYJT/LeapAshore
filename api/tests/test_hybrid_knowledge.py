from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.models import KnowledgeSearchRequest
from app.program_data import PROGRAMS
from app.services.hybrid_knowledge import retrieve_hybrid_knowledge


def test_hybrid_knowledge_maps_only_current_published_chunks_to_citations() -> None:
    program = PROGRAMS[0]
    version = SimpleNamespace(
        program_slug=program.slug,
        version_id="srcv_current",
        status="published",
        program=program,
        content_hash="a" * 64,
    )
    entity = {
        "chunk_id": "chunk-1", "text": "非 211 中国院校通常要求 70%。",
        "program_slug": program.slug, "section": "学术与背景",
        "source_version_id": "srcv_current", "source_content_hash": "a" * 64,
        "source_id": "source-1", "source_title": "Official source",
        "source_url": "https://example.edu/official", "verification_date": date.today().isoformat(),
    }

    class Index:
        def search_dense(self, _vector, **kwargs):
            assert kwargs["program_slugs"] == [program.slug]
            assert kwargs["degree_level"] == "授课型硕士"
            return [{"id": "chunk-1", "entity": entity}]

        def search_bm25(self, _query, **_kwargs):
            return [{"id": "chunk-1", "entity": entity}]

    class Embedder:
        def embed_query_sync(self, _query, *, cloud_processing_consented):
            assert cloud_processing_consented is True
            return [0.1, 0.2]

    response = retrieve_hybrid_knowledge(
        KnowledgeSearchRequest(query="UNSW 双非学生需要多少均分", target_degree_level="授课型硕士"),
        [version], index=Index(), embedder=Embedder(), cloud_processing_consented=True,
    )

    assert response.retrieval_version == "official-knowledge-hybrid-rrf-v1"
    assert len(response.hits) == 1
    assert response.hits[0].source.version_id == "srcv_current"
    assert response.hits[0].source.content_hash == "a" * 64
    assert response.hits[0].source.url == entity["source_url"]


def test_hybrid_knowledge_drops_superseded_version_before_return() -> None:
    program = PROGRAMS[0]
    version = SimpleNamespace(program_slug=program.slug, version_id="srcv_current", status="published", program=program, content_hash="a" * 64)
    stale = {"chunk_id": "old", "text": "old fact", "program_slug": program.slug,
             "source_version_id": "srcv_old", "source_content_hash": "b" * 64, "source_id": "s",
             "source_title": "t", "source_url": "https://example.edu", "verification_date": date.today().isoformat()}

    class Index:
        def search_dense(self, *_args, **_kwargs): return [{"id": "old", "entity": stale}]
        def search_bm25(self, *_args, **_kwargs): return []

    class Embedder:
        def embed_query_sync(self, *_args, **_kwargs): return [0.1]

    response = retrieve_hybrid_knowledge(KnowledgeSearchRequest(query="UNSW 要求"), [version], index=Index(), embedder=Embedder())
    assert response.hits == []
