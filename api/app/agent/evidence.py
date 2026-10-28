"""Retrieval and the evidence gate for questions about official requirements.

Answers about admission requirements come only from rows in the catalogue, each tied to an official
page. Before the model is allowed to answer, the gate checks:

1. a hit: the question names a school the catalogue holds;
2. a citable source: an https url, a title and a source id;
3. relevance: the hit's score clears ``MIN_SCORE``.

Verification status is not a gate condition but a label: a requirement whose source no human has
verified is still shown, marked 待核验 with its link, because the alternative — refusing every
question until the whole catalogue is verified — hides the official page the applicant needs.
Anything that fails the gate is refused and logged as a knowledge gap.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.program import Program
from app.models.source import Source

logger = logging.getLogger("leapashore.knowledge_gap")

# Spellings applicants actually use that the catalogue's own names do not cover.
UNIVERSITY_ALIASES: dict[str, tuple[str, ...]] = {
    "unsw": ("新南", "新南威尔士", "unsw"),
    "usyd": ("悉大", "悉尼大学", "usyd", "sydney uni", "university of sydney"),
    "monash": ("莫纳什", "蒙纳士", "monash"),
    "uq": ("昆大", "昆士兰", "uq", "queensland"),
    "uwa": ("西澳", "uwa", "western australia"),
}

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "信息技术": ("信息技术", "it", "information technology"),
    "计算机科学": ("计算机", "cs", "computer science", "计科"),
    "人工智能": ("人工智能", "ai", "artificial intelligence"),
    "数据科学": ("数据科学", "data science", "数据"),
}

SCHOOL_SCORE = 2
FIELD_SCORE = 1
MIN_SCORE = SCHOOL_SCORE  # a hit must at least name the school


@dataclass
class Hit:
    program: Program
    source: Source | None
    score: int


def _mentions(text: str, words: tuple[str, ...]) -> bool:
    return any(w.lower() in text for w in words if w)


def search_requirements(session: Session, query: str, limit: int = 4) -> list[Hit]:
    """Score every catalogue program against the question and return the best hits."""
    q = query.lower()
    programs = session.scalars(
        select(Program).options(selectinload(Program.university), selectinload(Program.prerequisites))
    ).all()
    hits: list[Hit] = []
    for p in programs:
        uni = p.university
        school_words = (uni.name, uni.name_en or "", *UNIVERSITY_ALIASES.get(uni.id, ()))
        score = SCHOOL_SCORE if _mentions(q, school_words) else 0
        for canonical, words in FIELD_ALIASES.items():
            if canonical in (p.name or "") and _mentions(q, words):
                score += FIELD_SCORE
                break
        if score:
            hits.append(Hit(p, session.get(Source, p.source_id), score))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def _citable(source: Source | None) -> bool:
    return bool(source and source.id and source.title and (source.url or "").startswith("https://"))


def _fmt_mark(value) -> str:
    return "未知" if value is None else f"{float(value):g}"


def evidence_line(n: int, hit: Hit) -> str:
    p, s = hit.program, hit.source
    prereqs = "；".join(x.label for x in sorted(p.prerequisites, key=lambda x: x.sort_order)) or "无"
    status = "已核验" if (s and s.verified_at) else "待核验"
    return (
        f"[{n}] {p.university.name} {p.name}（{p.name_en}）"
        f"｜均分要求（211/985）：{_fmt_mark(p.minimum_mark)}"
        f"｜均分要求（非211）：{_fmt_mark(p.non_211_minimum_mark)}"
        f"｜语言：{p.english_requirement or '未知'}"
        f"｜先修要求：{prereqs}"
        f"｜数据状态：{status}"
        f"｜来源：{s.title if s else '无'} {s.url if s else ''}"
    )


def gate(session: Session, query: str) -> dict:
    """Run retrieval and the gate. Returns the state update for the graph."""
    hits = search_requirements(session, query)
    # A field match alone ("计算机") is not a hit: it would answer a question about an uncollected
    # school with another school's requirements.
    relevant = [h for h in hits if h.score >= MIN_SCORE]
    strong = [h for h in relevant if _citable(h.source)]
    signals = {
        "hits": len(hits),
        "relevant": len(relevant),
        "top_score": hits[0].score if hits else 0,
        "citable": len(strong),
    }
    if not strong:
        reason = "no_hit" if not relevant else "no_citable_source"
        logger.warning("knowledge gap reason=%s query=%r signals=%s", reason, query, signals)
        return {
            "evidence_strong": False,
            "refusal": reason,
            "citations": [],
            "trace": {"evidence_gate": "weak", "gate_signals": signals},
        }
    citations = [
        {
            "n": i + 1,
            "programId": h.program.id,
            "program": f"{h.program.university.name} {h.program.name}",
            "title": h.source.title,
            "url": h.source.url,
            "status": "已核验" if h.source.verified_at else "待核验",
        }
        for i, h in enumerate(strong)
    ]
    return {
        "evidence_strong": True,
        "evidence": "\n".join(evidence_line(i + 1, h) for i, h in enumerate(strong)),
        "citations": citations,
        "trace": {"evidence_gate": "strong", "gate_signals": signals},
    }
