from app.models import KnowledgeSearchRequest
from app.services.knowledge_rag import grounded_fallback_answer, retrieve_official_knowledge


def test_rag_retrieves_official_evidence_with_source_metadata() -> None:
    response = retrieve_official_knowledge(KnowledgeSearchRequest(query="UQ 数据科学雅思和数学先修要求", top_k=3))
    assert response.retrieval_version == "official-knowledge-bm25-1.0.0"
    assert response.hits[0].program_slug == "uq-master-data-science"
    assert response.hits[0].section == "先修课与语言"
    assert response.hits[0].source.url.startswith("https://")
    assert response.hits[0].source.verified_at
    assert "仅检索已完成人工核验" in response.coverage_notice


def test_rag_filters_program_scope_and_returns_grounded_no_model_answer() -> None:
    response = retrieve_official_knowledge(KnowledgeSearchRequest(
        query="雅思和数学要求",
        program_slugs=["uwa-master-it"],
        top_k=3,
    ))
    assert response.hits
    assert {hit.program_slug for hit in response.hits} == {"uwa-master-it"}
    answer = grounded_fallback_answer(response.query, response.hits)
    assert answer
    assert "西澳大学" in answer
    assert "https://www.uwa.edu.au/" in answer
    assert "不是录取承诺" in answer


def test_rag_returns_honest_empty_state_outside_verified_corpus() -> None:
    response = retrieve_official_knowledge(KnowledgeSearchRequest(
        query="量子考古学项目要求",
        program_slugs=["not-a-verified-program"],
    ))
    assert response.hits == []
    assert "没有可引用" in response.coverage_notice
