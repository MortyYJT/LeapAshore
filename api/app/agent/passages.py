"""Retrieval and the gate for questions the official pages answer and the catalogue's columns do not
(openspec snapshot-rag D6, D7): tuition, recommendation letters, interviews.

The scope is the schools the question names (the same recognition and country narrowing as the
requirement gate). When it names a subject, only the pages of that subject's programs and the pages no
single program owns (a fees or admissions page) are searched, so another programme's fee is never
evidence for this one. Inside the scope the chunks that state the topic are ranked by full text
(`fts`); with a question vector, `vector` and `hybrid` (RRF, as `evidence`) rank them too. At most
`PER_PAGE` chunks come from one page and the schools take turns, `TOP_K` passages in all.

Nothing is answered here: the passages go to `answer.py`, which checks every quote the model gives.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from sqlalchemy import Float, and_, case, cast, func, literal, null, or_, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from app.agent import catalog_match, embeddings, evidence
from app.config import settings
from app.models.program import Program
from app.models.snapshot import SnapshotChunk, SnapshotChunkEmbedding, SnapshotPage

logger = logging.getLogger("leapashore.knowledge_gap")

TOPICS_FILE = catalog_match.DATA_DIR / "page_topics.json"
# Passages handed to the model: about 7,000 characters at most (chunks are at most 1,200).
TOP_K = 6
PER_PAGE = 2
# The intents whose questions about a page topic are answered from the pages. Planning, profile and
# task messages keep their own routes even when they mention a fee.
INTENTS = ("官方要求核验", "通用问答")


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    search: tuple[str, ...]


@lru_cache(maxsize=1)
def _topics() -> list[tuple[Topic, tuple[str, ...]]]:
    data = json.loads(TOPICS_FILE.read_text(encoding="utf-8"))["topics"]
    return [(Topic(t["key"], t["label"], tuple(t["search"])), tuple(catalog_match.normalize(x) for x in t["terms"]))
            for t in data]


def detect_topics(question: str) -> list[Topic]:
    """The page topics a question asks about, in file order."""
    text = catalog_match.normalize(question)
    return [topic for topic, terms in _topics() if any(catalog_match._find(text, term) for term in terms)]


def names_a_school(session: Session, question: str) -> bool:
    index = catalog_match.school_index(evidence._school_rows(session))
    return bool(index.match_groups(catalog_match.normalize(question)))


def route(session: Session, question: str, intent: str) -> list[Topic]:
    """The topics to answer from the pages, or [] when the question keeps its intent's route."""
    if intent not in INTENTS:
        return []
    topics = detect_topics(question)
    return topics if topics and names_a_school(session, question) else []


@dataclass
class Passage:
    chunk_id: str
    text: str
    url: str
    title: str | None
    school: str  # the school's display name
    program: str | None  # the program whose page it is, if one
    fetched_at: datetime | None

    def header(self, n: int) -> str:
        page = f"{self.program}（项目页面）" if self.program else (self.title or "学校官方页面")
        date = self.fetched_at.date().isoformat() if self.fetched_at else "日期未知"
        return f"[{n}] {self.school}｜{page}｜{self.url}｜抓取于 {date}"


@dataclass
class PassageRetrieval:
    schools: list[str]
    school_names: dict[str, str]
    topics: list[Topic]
    passages: list[Passage] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    subject_words: list[str] = field(default_factory=list)
    narrowing_pattern: str | None = None
    pages_in_school: int = 0  # every stored page of the named schools
    pages_in_scope: int = 0  # ... of those, the ones the subject allows
    ranking: str = "fts"


def _topic_query(topics: list[Topic]):
    branches = [func.phraseto_tsquery(literal(evidence.TS_CONFIG, REGCONFIG), term)
                for topic in topics for term in topic.search]
    query = branches[0]
    for branch in branches[1:]:
        query = query.op("||")(branch)
    return query


def search_passages(session: Session, question: str, topics: list[Topic], ranking: str = "fts",
                    query_vector: list[float] | None = None, limit: int = TOP_K) -> PassageRetrieval:
    index = catalog_match.school_index(evidence._school_rows(session))
    parsed = catalog_match.parse(index, question)
    schools = evidence._in_countries(session, parsed.school_groups, parsed.countries)
    found = PassageRetrieval(schools=schools, school_names={u: index.names[u] for u in schools}, topics=topics,
                             fields=parsed.fields, subject_words=parsed.subject_words,
                             narrowing_pattern=parsed.narrowing_pattern,
                             ranking=evidence._effective_ranking(ranking, query_vector))
    if not schools or not topics:
        return found
    in_schools = SnapshotPage.university_id.in_(schools)
    found.pages_in_school = session.scalar(select(func.count()).select_from(SnapshotPage).where(in_schools)) or 0
    scope = [in_schools]
    if parsed.fields:
        fits = Program.field.in_(parsed.fields)
        if parsed.narrowing_pattern:
            fits = and_(fits, Program.name_en.regexp_match(parsed.narrowing_pattern, "i"))
        fitting = select(Program.id).where(Program.university_id.in_(schools), fits)
        scope.append(or_(SnapshotPage.program_id.is_(None), SnapshotPage.program_id.in_(fitting)))
    found.pages_in_scope = session.scalar(select(func.count()).select_from(SnapshotPage).where(*scope)) or 0
    if not found.pages_in_scope:
        return found

    tsq = _topic_query(topics)
    matches = SnapshotChunk.search_tsv.op("@@")(tsq)
    fts_score = case((matches, func.ts_rank_cd(SnapshotChunk.search_tsv, tsq, 1)), else_=null())
    use_vectors = found.ranking in ("vector", "hybrid")
    distance = (SnapshotChunkEmbedding.embedding.cosine_distance(query_vector) if use_vectors
                else cast(null(), Float))
    # Every ranking reads the same chunks, those that state the topic; vectors only reorder them. A
    # vector alone would let any embedded chunk of the school in, and a school whose pages never
    # mention the topic would no longer be refused (review of #60).
    wanted = matches
    scoped = (
        select(SnapshotChunk.id, SnapshotChunk.page_id, SnapshotChunk.ordinal, SnapshotPage.university_id,
               fts_score.label("fts_score"), distance.label("distance"))
        .join(SnapshotPage, SnapshotPage.id == SnapshotChunk.page_id)
        .outerjoin(SnapshotChunkEmbedding, and_(SnapshotChunkEmbedding.chunk_id == SnapshotChunk.id,
                                                SnapshotChunkEmbedding.model == settings.embed_model))
        .where(*scope, wanted)
        .subquery()
    )
    c = scoped.c
    fts_rank = func.rank().over(partition_by=c.university_id, order_by=c.fts_score.desc().nulls_last())
    vec_rank = func.rank().over(partition_by=c.university_id, order_by=c.distance.asc().nulls_last())
    lists = select(
        c.id, c.page_id, c.ordinal, c.university_id,
        case((c.fts_score.is_not(None), 1.0 / (evidence.RRF_K + fts_rank)), else_=0.0).label("rrf_fts"),
        case((c.distance.is_not(None), 1.0 / (evidence.RRF_K + vec_rank)), else_=0.0).label("rrf_vec"),
    ).subquery()
    score = {"fts": lists.c.rrf_fts, "vector": lists.c.rrf_vec, "hybrid": lists.c.rrf_fts + lists.c.rrf_vec}[found.ranking]
    order = (score.desc(), lists.c.page_id, lists.c.ordinal)
    per_page = select(
        lists.c.id, lists.c.university_id, score.label("score"), lists.c.page_id, lists.c.ordinal,
        func.row_number().over(partition_by=lists.c.page_id, order_by=order).label("in_page"),
    ).subquery()
    p = per_page.c
    per_school = select(
        p.id, p.university_id,
        func.row_number().over(partition_by=p.university_id,
                               order_by=(p.score.desc(), p.page_id, p.ordinal)).label("rn"),
    ).where(p.in_page <= PER_PAGE).subquery()
    rows = session.execute(select(per_school.c.id, per_school.c.university_id, per_school.c.rn)
                           .where(per_school.c.rn <= limit)).all()
    turn = {uid: i for i, uid in enumerate(schools)}
    rows.sort(key=lambda r: (r.rn, turn[r.university_id]))
    chosen = [r.id for r in rows[:limit]]
    if not chosen:
        return found
    details = {
        r.id: r for r in session.execute(
            select(SnapshotChunk.id, SnapshotChunk.text, SnapshotPage.url, SnapshotPage.title, SnapshotPage.university_id,
                   SnapshotPage.fetched_at, Program.name.label("program"))
            .join(SnapshotPage, SnapshotPage.id == SnapshotChunk.page_id)
            .outerjoin(Program, Program.id == SnapshotPage.program_id)
            .where(SnapshotChunk.id.in_(chosen))
        )
    }
    found.passages = [
        Passage(chunk_id=cid, text=details[cid].text, url=details[cid].url, title=details[cid].title,
                school=found.school_names.get(details[cid].university_id, details[cid].university_id),
                program=details[cid].program, fetched_at=details[cid].fetched_at)
        for cid in chosen
    ]
    return found


def _topic_label(topics: list[Topic]) -> str:
    return "、".join(t.label for t in topics)


def refusal(session: Session, found: PassageRetrieval) -> tuple[str, str]:
    tail = "我不能凭印象回答，以免你照着错误的信息去申请。已记录为待采集。"
    if not found.schools:
        return evidence.refusal(session, evidence.Retrieval(schools=[], fields=[], hits=[]))
    names = "、".join(dict.fromkeys(found.school_names[u] for u in found.schools))
    topic = _topic_label(found.topics)
    if not found.pages_in_school:
        return "school_not_collected", f"{names}还没有收录官方页面，查不到{topic}。{tail}"
    if not found.pages_in_scope:
        subject = "、".join(found.subject_words) or "、".join(found.fields)
        return "no_program_in_field", (
            f"{names}已收录的 {found.pages_in_school} 个官方页面里没有「{subject}」方向项目的页面，查不到它的{topic}。{tail}"
        )
    return "no_passage", (
        f"{names}已收录的 {found.pages_in_scope} 个相关官方页面里没有找到写{topic}的段落。{tail}"
    )


def gate(session: Session, question: str, topics: list[Topic], ranking: str | None = None) -> dict:
    """Retrieve the passages; the state update for the graph. No passage: a refusal worded from counts."""
    ranking = ranking or settings.advisor_retrieval
    vector = embeddings.embed_query(question) if ranking in ("vector", "hybrid") else None
    found = search_passages(session, question, topics, ranking=ranking, query_vector=vector)
    signals = {"schools": found.schools, "topics": [t.key for t in topics], "fields": found.fields,
               "pages_in_school": found.pages_in_school, "pages_in_scope": found.pages_in_scope,
               "passages": len(found.passages), "ranking": found.ranking, "subject_words": found.subject_words}
    if not found.passages:
        reason, text = refusal(session, found)
        logger.warning("knowledge gap reason=%s query=%r signals=%s", reason, question, signals)
        return {"evidence_strong": False, "refusal": reason, "refusal_text": text, "passages": [], "citations": [],
                "trace": {"evidence_gate": "weak", "gate_signals": signals}}
    return {
        "evidence_strong": True,
        "passages": [passage_dict(p) for p in found.passages],
        "trace": {"evidence_gate": "strong", "gate_signals": signals,
                  "passage_chunks": [p.chunk_id for p in found.passages]},
    }


def passage_dict(p: Passage) -> dict:
    """A passage as the graph state keeps it (JSON, so the checkpointer can store it)."""
    return {"chunk_id": p.chunk_id, "text": p.text, "url": p.url, "title": p.title, "school": p.school,
            "program": p.program, "fetched_at": p.fetched_at.isoformat() if p.fetched_at else None}
