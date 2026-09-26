from datetime import UTC, datetime, timedelta

from app.models import KnowledgeEvidence, SourceCitation
from app.services.confidence import evaluate_evidence


def hit(*, score: float = 5.0, url: str = "https://example.edu/course", days_old: int = 5) -> KnowledgeEvidence:
    verified = (datetime.now(UTC).date() - timedelta(days=days_old)).isoformat()
    return KnowledgeEvidence(
        chunk_id="chunk-1",
        program_slug="uq-master-data-science",
        university="昆士兰大学",
        program_name="Master of Data Science",
        section="先修课与语言",
        content="IELTS 6.5，数学或统计先修要求。",
        relevance_score=score,
        source=SourceCitation(id="source-1", title="Official course", url=url, excerpt="facts", verified_at=verified),
    )


def test_evidence_gate_accepts_recent_relevant_official_citation() -> None:
    result = evaluate_evidence([hit()])
    assert result.allowed is True
    assert result.reason == "sufficient_evidence"


def test_evidence_gate_rejects_low_score_missing_or_invalid_citation() -> None:
    assert evaluate_evidence([]).reason == "no_evidence"
    assert evaluate_evidence([hit(score=1.0)]).reason == "low_relevance"
    assert evaluate_evidence([hit(url="http://example.edu/course")]).reason == "invalid_citation"


def test_evidence_gate_rejects_stale_source() -> None:
    result = evaluate_evidence([hit(days_old=366)])
    assert result.allowed is False
    assert result.reason == "stale_source"
