from datetime import UTC, datetime
from hashlib import sha256

from ..models import KnowledgeGapCandidate
from ..services.knowledge_rag import infer_program_slugs


def knowledge_gap_candidate(query: str, *, now: datetime | None = None) -> KnowledgeGapCandidate:
    """Aggregate gaps by official program and topic; never persist raw query or user identity."""
    text = query.casefold()
    topic = (
        "tuition" if any(term in text for term in ("学费", "费用", "tuition", "fee")) else
        "deadline" if any(term in text for term in ("截止", "deadline", "due date")) else
        "language" if any(term in text for term in ("雅思", "ielts", "英语", "语言", "english")) else
        "prerequisite" if any(term in text for term in ("先修", "课程", "数学", "算法", "prerequisite", "coursework")) else
        "academic" if any(term in text for term in ("成绩", "均分", "gpa", "背景", "录取", "入学", "mark", "admission")) else
        "policy" if any(term in text for term in ("政策", "policy", "要求", "requirement")) else
        "general"
    )
    slugs = infer_program_slugs(query)
    program_slug = slugs[0] if len(slugs) == 1 else None
    normalized = f"{program_slug or 'unscoped'}\0{topic}"
    candidate_hash = sha256(normalized.encode()).hexdigest()
    timestamp = now or datetime.now(UTC)
    return KnowledgeGapCandidate(
        id=f"kgap_{candidate_hash[:24]}",
        candidate_hash=candidate_hash,
        program_slug=program_slug,
        topic_class=topic,
        created_at=timestamp,
        updated_at=timestamp,
    )


def knowledge_gap_eval_query(candidate: KnowledgeGapCandidate, program_name: str, university: str) -> str:
    topic_query = {
        "academic": "成绩 均分 GPA 入学背景要求",
        "prerequisite": "先修课程 数学 算法要求",
        "language": "IELTS 英语语言要求",
        "tuition": "学费 tuition fee",
        "deadline": "申请截止日期 deadline",
        "policy": "官方政策 requirement",
        "general": "项目官方要求",
    }[candidate.topic_class]
    # University is included to narrow ambiguous course aliases before retrieval.
    return f"{university} {program_name} {topic_query}"
