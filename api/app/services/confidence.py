from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

from ..models import KnowledgeEvidence

CONFIDENCE_GATE_VERSION = "evidence-gate-v1"
MIN_RELEVANCE_SCORE = 4.0
MAX_SOURCE_AGE_DAYS = 365


@dataclass(frozen=True)
class EvidenceDecision:
    allowed: bool
    reason: str
    source_count: int
    top_relevance_score: float
    gate_version: str = CONFIDENCE_GATE_VERSION


def evaluate_evidence(
    hits: list[KnowledgeEvidence],
    *,
    today: date | None = None,
    min_relevance_score: float = MIN_RELEVANCE_SCORE,
    max_source_age_days: int = MAX_SOURCE_AGE_DAYS,
) -> EvidenceDecision:
    """Fail closed unless evidence is relevant, current enough, and citeable.

    This is a deterministic evidence sufficiency rule, not a calibrated probability.
    """
    top_score = max((hit.relevance_score for hit in hits), default=0.0)
    if not hits:
        return EvidenceDecision(False, "no_evidence", 0, top_score)
    if any(
        not hit.source.id
        or urlparse(hit.source.url).scheme != "https"
        or not urlparse(hit.source.url).netloc
        or not hit.source.title
        for hit in hits
    ):
        return EvidenceDecision(False, "invalid_citation", len(hits), top_score)
    current_date = today or date.today()
    for hit in hits:
        try:
            verified = date.fromisoformat(hit.source.verified_at)
        except (TypeError, ValueError):
            return EvidenceDecision(False, "invalid_verification_date", len(hits), top_score)
        age = (current_date - verified).days
        if age < 0 or age > max_source_age_days:
            return EvidenceDecision(False, "stale_source", len(hits), top_score)
    if top_score < min_relevance_score:
        return EvidenceDecision(False, "low_relevance", len(hits), top_score)
    return EvidenceDecision(True, "sufficient_evidence", len(hits), top_score)
