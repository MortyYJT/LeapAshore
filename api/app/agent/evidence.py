"""Retrieval and the evidence gate for questions about official requirements.

Answers about admission requirements come only from rows in the catalogue, each tied to an official
page. Before the model is allowed to answer, the gate checks:

1. a school: the question names a school the catalogue holds (any spelling `catalog_match` knows);
2. requirement data: the row states at least one requirement (English, a mark, a prerequisite, an
   academic requirement, a deadline; `has_requirement_data`);
   a row that only names a course (the CRICOS extract) cannot answer a requirement question;
3. a citable source: an https url and a title;
4. a subject, when the question names one: the row's `Program.field` is that subject's area.

Verification status is not a gate condition but a label: a requirement whose source no human has
verified is still shown, marked 待核验 with its link, because the alternative — refusing every
question until the whole catalogue is verified — hides the official page the applicant needs.

The filtering runs in SQL, so a question reads the universities table (about 165 rows) and at most
``TOP_K`` program rows per named school, never the whole catalogue. Anything that fails the gate is
refused with a reason and a text built from the catalogue's own counts, and logged as a knowledge gap.

Inside that scope the rows are ordered by one of four rankings (openspec hybrid-retrieval D7):
``rules`` (the subject's name pattern, P0 #4), ``fts`` (PostgreSQL full text over the program's names),
``vector`` (cosine distance to the question's bge-m3 vector) and ``hybrid`` (Reciprocal Rank Fusion of
the last two). The ranking changes the order only; which rows may be evidence is the same for all four.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Float, and_, case, cast, func, literal, null, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session, joinedload, selectinload

from app.agent import catalog_match, embeddings
from app.config import settings
from app.models.program import Program, ProgramEmbedding, University, has_requirement_data
from app.models.source import Source

logger = logging.getLogger("leapashore.knowledge_gap")

# The number of program rows the gate hands the model. The eval reads it from here, so "K" in
# Recall@K is what the code returns.
TOP_K = 4

MACHINE_CHECKED = "机器核对"

RANKINGS = ("rules", "fts", "vector", "hybrid")
# Reciprocal Rank Fusion's constant (Cormack, Clarke and Buettcher, SIGIR 2009): a row's score is the
# sum of 1 / (RRF_K + its rank) over the lists it is in. 60 is the paper's value, not tuned here.
RRF_K = 60
# The text-search configuration of `programs.search_tsv` (alembic e3a9c5d17b42).
TS_CONFIG = "english"


def citable_source():
    """SQL twin of `_citable`, for rows joined to their source."""
    return and_(Source.url.like("https://%"), Source.title.is_not(None), Source.title != "")


@dataclass
class Hit:
    program: Program
    source: Source | None


@dataclass
class Retrieval:
    schools: list[str]  # university ids the question names, in order of mention
    fields: list[str]  # Program.field areas the question names
    hits: list[Hit]
    school_names: dict[str, str] = field(default_factory=dict)
    missing_schools: list[str] = field(default_factory=list)  # named, but nothing matched there
    subject_words: list[str] = field(default_factory=list)
    narrowing_pattern: str | None = None  # set when a specific subject was named ("金融", not "商科")
    subject_fallback: bool = False  # ... but no returned row's name fits it; these are its broader area
    countries: list[str] = field(default_factory=list)  # countries named; they narrow `schools` (D6)
    fts_terms: list[str] = field(default_factory=list)
    ranking: str = "rules"  # the ranking actually used, after any fallback


def _school_rows(session: Session) -> list[tuple[str, str | None, str | None]]:
    return [tuple(r) for r in session.execute(select(University.id, University.name, University.name_en))]


def _in_countries(session: Session, groups: list[list[str]], countries: list[str]) -> list[str]:
    """The named schools, in mention order, with each shared name narrowed to the named countries.

    A country only tells apart schools that share the name it qualifies ("英国的纽卡斯尔大学"): a
    school named without ambiguity is kept whatever country the question mentions ("我在英国读本科，
    问港大和 UCL" keeps 港大; found in review). A shared name none of whose schools is in a named
    country keeps all of them."""
    schools = list(dict.fromkeys(u for g in groups for u in g))
    ambiguous = [g for g in groups if len(g) > 1]
    if not countries or not ambiguous:
        return schools
    there = set(session.scalars(
        select(University.id).where(University.id.in_([u for g in ambiguous for u in g]),
                                    University.country.in_(countries))
    ))
    kept = []
    for group in groups:
        narrowed = [u for u in group if u in there] if len(group) > 1 else group
        kept.extend(narrowed or group)
    return list(dict.fromkeys(kept))


def _tsquery(terms: list[str]):
    """One OR branch per term; inside a term every word must appear ("computer science")."""
    branches = [func.plainto_tsquery(literal(TS_CONFIG, REGCONFIG), t) for t in terms]
    query = branches[0]
    for branch in branches[1:]:
        query = query.op("||")(branch)
    return query


def _effective_ranking(ranking: str, query_vector) -> str:
    if ranking not in RANKINGS:
        raise ValueError(f"unknown ranking {ranking!r}; expected one of {RANKINGS}")
    if ranking in ("vector", "hybrid") and query_vector is None:
        return "fts"
    return ranking


def search_requirements(session: Session, query: str, limit: int = TOP_K, ranking: str = "rules",
                        query_vector: list[float] | None = None) -> Retrieval:
    """The rows that can answer a requirement question about the schools and subject it names.

    Rows are taken in turn from each named school (row 1 of every school, then row 2, ...), so a
    question comparing two schools gets evidence for both. Inside a school, when a specific subject
    was named, only rows whose English name fits it are kept (when there are any); the order among the
    kept rows is `ranking`'s. `vector` and `hybrid` need `query_vector`; without it they rank by full
    text, and `Retrieval.ranking` says so.
    """
    index = catalog_match.school_index(_school_rows(session))
    parsed = catalog_match.parse(index, query)
    schools = _in_countries(session, parsed.school_groups, parsed.countries)
    result = Retrieval(schools=schools, fields=parsed.fields, hits=[],
                       school_names={u: index.names[u] for u in schools},
                       subject_words=parsed.subject_words, narrowing_pattern=parsed.narrowing_pattern,
                       countries=parsed.countries, fts_terms=parsed.fts_terms,
                       ranking=_effective_ranking(ranking, query_vector))
    if not schools:
        return result

    name_fit = (
        case((Program.name_en.regexp_match(parsed.name_pattern, "i"), 1), else_=0)
        if parsed.name_pattern else literal(0)
    )
    narrow_fit = (
        case((Program.name_en.regexp_match(parsed.narrowing_pattern, "i"), 1), else_=0)
        if parsed.narrowing_pattern else literal(0)
    )
    checked = case((Program.data_status == MACHINE_CHECKED, 1), else_=0)
    usable = case((and_(has_requirement_data(), citable_source()), 1), else_=0)
    if parsed.fts_terms:
        tsq = _tsquery(parsed.fts_terms)
        # Normalisation 1 divides by 1 + log(length): of two names that both say "statistics", the one
        # that says little else comes first.
        fts_score = case((Program.search_tsv.op("@@")(tsq), func.ts_rank_cd(Program.search_tsv, tsq, 1)),
                         else_=null())
    else:
        fts_score = cast(null(), Float)
    if result.ranking in ("vector", "hybrid"):
        distance = ProgramEmbedding.embedding.cosine_distance(query_vector)
    else:
        distance = cast(null(), Float)
    scope = [Program.university_id.in_(schools)]
    if parsed.fields:
        scope.append(Program.field.in_(parsed.fields))
    # 1. Every row of the named schools in the named areas, with what the next steps need. The best
    #    name fit is taken over all of them, with or without requirement data: when a specific
    #    subject ("数据科学") fits a school's rows only where nothing has been collected yet, the
    #    school answers nothing rather than a neighbouring programme's requirements.
    in_scope = (
        select(
            Program.id, Program.university_id, Program.name,
            name_fit.label("rank_fit"), narrow_fit.label("fit"), checked.label("checked"), usable.label("usable"),
            func.max(narrow_fit).over(partition_by=Program.university_id).label("best_fit"),
            fts_score.label("fts_score"), distance.label("distance"),
        )
        .join(Source, Source.id == Program.source_id)
        .outerjoin(ProgramEmbedding, and_(ProgramEmbedding.program_id == Program.id,
                                          ProgramEmbedding.model == settings.embed_model))
        .where(*scope)
        .subquery()
    )
    # 2. The usable rows that fit as well as the school's best: each list's rank per school, then the
    #    ranking's score. A row missing from a list (no full-text match, no vector) adds nothing.
    c = in_scope.c
    usable_rows = and_(c.usable == 1, c.fit == c.best_fit)
    fts_rank = func.rank().over(partition_by=c.university_id, order_by=c.fts_score.desc().nulls_last())
    vec_rank = func.rank().over(partition_by=c.university_id, order_by=c.distance.asc().nulls_last())
    lists = (
        select(
            c.id, c.university_id, c.name, c.rank_fit, c.checked,
            case((c.fts_score.is_not(None), 1.0 / (RRF_K + fts_rank)), else_=0.0).label("rrf_fts"),
            case((c.distance.is_not(None), 1.0 / (RRF_K + vec_rank)), else_=0.0).label("rrf_vec"),
        )
        .where(usable_rows)
        .subquery()
    )
    score = {
        "rules": lists.c.rank_fit,
        "fts": lists.c.rrf_fts,
        "vector": lists.c.rrf_vec,
        "hybrid": lists.c.rrf_fts + lists.c.rrf_vec,
    }[result.ranking]
    ranked = (
        select(
            lists.c.id, lists.c.university_id,
            func.row_number().over(
                partition_by=lists.c.university_id,
                order_by=(score.desc(), lists.c.checked.desc(), lists.c.name, lists.c.id),
            ).label("rn"),
        )
        .subquery()
    )
    # 3. Each school's first `limit` rows, so the rows returned stay bounded by schools x K.
    candidates = session.execute(
        select(ranked.c.id, ranked.c.university_id, ranked.c.rn).where(ranked.c.rn <= limit)
    ).all()
    order = {uid: i for i, uid in enumerate(schools)}
    candidates.sort(key=lambda r: (r.rn, order[r.university_id]))
    chosen = [r.id for r in candidates[:limit]]
    # A name two rows share (a CRICOS row and an empty one, "墨尔本大学") is only missing when
    # neither row matched.
    matched_names = {index.names[r.university_id] for r in candidates}
    result.missing_schools = [
        u for u in schools
        if u not in {r.university_id for r in candidates} and index.names[u] not in matched_names
    ]
    if not chosen:
        return result

    programs = session.scalars(
        select(Program)
        .where(Program.id.in_(chosen))
        .options(joinedload(Program.university), selectinload(Program.prerequisites),
                 selectinload(Program.deadlines))
    ).all()
    sources = {s.id: s for s in session.scalars(select(Source).where(Source.id.in_({p.source_id for p in programs})))}
    by_id = {p.id: p for p in programs}
    result.hits = [Hit(by_id[pid], sources.get(by_id[pid].source_id)) for pid in chosen]
    if parsed.narrowing_pattern:
        fits = re.compile(parsed.narrowing_pattern, re.IGNORECASE)
        result.subject_fallback = not any(fits.search(h.program.name_en or "") for h in result.hits)
    return result


def _citable(source: Source | None) -> bool:
    return bool(source and source.id and source.title and (source.url or "").startswith("https://"))


def _fmt_mark(value) -> str:
    return "未知" if value is None else f"{float(value):g}"


BEIJING = timezone(timedelta(hours=8))


def beijing_today() -> date:
    """Today's calendar date in Beijing, the day a deadline is judged against (requirement-dates D4)."""
    return datetime.now(BEIJING).date()


def _page(url: str | None, source: Source | None) -> str:
    """Name the page a value was read from when it is not the program's own cited page."""
    return f"（出处 {url}）" if url and (source is None or url != source.url) else ""


def _deadlines(p: Program, source: Source | None, today: date) -> str:
    """Every collected deadline, a past one marked 已截止 so the model cannot present it as open, and
    one read from a shared page naming that page, so the citation points where the date is."""
    parts = []
    for row in sorted(p.deadlines, key=lambda x: x.sort_order):
        text = f"{row.label} {row.deadline.isoformat()}" if row.label else row.deadline.isoformat()
        parts.append(text + ("（已截止）" if row.deadline < today else "") + _page(row.source_url, source))
    return "；".join(parts) or "未知"


def _academic(p: Program, source: Source | None) -> str:
    if not p.academic_requirement:
        return "未知"
    return p.academic_requirement + _page(getattr(p, "academic_source_url", None), source)


def evidence_line(n: int, hit: Hit, today: date | None = None) -> str:
    p, s = hit.program, hit.source
    prereqs = "；".join(x.label for x in sorted(p.prerequisites, key=lambda x: x.sort_order)) or "无"
    status = "已核验" if (s and s.verified_at) else "待核验"
    return (
        f"[{n}] {p.university.name} {p.name}（{p.name_en}）"
        f"｜均分要求（211/985）：{_fmt_mark(p.minimum_mark)}"
        f"｜均分要求（非211）：{_fmt_mark(p.non_211_minimum_mark)}"
        f"｜语言：{p.english_requirement or '未知'}"
        f"｜学术要求：{_academic(p, s)}"
        f"｜申请截止：{_deadlines(p, s, today or beijing_today())}"
        f"｜先修要求：{prereqs}"
        f"｜数据状态：{status}"
        f"｜来源：{s.title if s else '无'} {s.url if s else ''}"
    )


# ---- refusals, worded from the catalogue's own counts -------------------------------------------


def _join_names(names: list[str]) -> str:
    return "、".join(names)


_COUNTS_TTL = 600.0
_counts_cache: dict[str, tuple[float, tuple[int, int, list[str]]]] = {}


def _catalogue_counts(session: Session) -> tuple[int, int, list[str]]:
    """Schools and programs that can answer a requirement question, and the three largest schools.

    This aggregates the whole catalogue, so it is kept for ten minutes: it only words a refusal, and
    an import moves it by a few rows at most.
    """
    cached = _counts_cache.get("counts")
    if cached and time.monotonic() - cached[0] < _COUNTS_TTL:
        return cached[1]
    counts = _count_catalogue(session)
    _counts_cache["counts"] = (time.monotonic(), counts)
    return counts


def _count_catalogue(session: Session) -> tuple[int, int, list[str]]:
    answerable = (
        select(Program.university_id, func.count().label("n"))
        .join(Source, Source.id == Program.source_id)
        .where(has_requirement_data(), citable_source())
        .group_by(Program.university_id)
        .subquery()
    )
    schools, programs = session.execute(
        select(func.count(), func.coalesce(func.sum(answerable.c.n), 0)).select_from(answerable)
    ).one()
    examples = session.scalars(
        select(University.name).join(answerable, answerable.c.university_id == University.id)
        .order_by(answerable.c.n.desc(), University.id).limit(3)
    ).all()
    return int(schools), int(programs), list(examples)


def _scope_counts(session: Session, found: "Retrieval") -> dict:
    """What the named schools hold: all rows and rows with requirement data, overall, inside the
    named areas, and among the rows whose name fits a specific subject."""
    in_field = Program.field.in_(found.fields) if found.fields else literal(True)
    fits = (
        Program.name_en.regexp_match(found.narrowing_pattern, "i") if found.narrowing_pattern else literal(False)
    )
    data = has_requirement_data()
    row = session.execute(
        select(
            func.count(),
            func.count().filter(data),
            func.count().filter(in_field),
            func.count().filter(and_(in_field, data)),
            func.count().filter(and_(in_field, fits)),
            func.count().filter(and_(in_field, fits, data)),
        )
        .select_from(Program)
        .join(Source, Source.id == Program.source_id)
        .where(Program.university_id.in_(found.schools))
    ).one()
    return dict(zip(("programs", "with_data", "in_field", "in_field_with_data", "fitting", "fitting_with_data"), row))


def _subject_label(found: "Retrieval") -> str:
    words = "、".join(found.subject_words)
    areas = "、".join(found.fields)
    return f"「{words}」（{areas}）" if words else f"「{areas}」"


def refusal(session: Session, found: Retrieval) -> tuple[str, str]:
    """Why the gate refused, and the sentence the applicant sees."""
    tail = "我不能凭印象回答，以免你照着错误的要求去申请。已记录为待采集。"
    if not found.schools:
        schools, programs, examples = _catalogue_counts(session)
        example = f"（例如{_join_names(examples)}）" if examples else ""
        return "no_school", (
            f"这个问题里没有认出已收录官方要求的学校。目前收录了 {schools} 所学校、{programs:,} 个项目的官方录取要求，"
            f"请写出学校全称或常用简称{example}再问一次。没有收录的学校，{tail}"
        )
    names = _join_names(list(dict.fromkeys(found.school_names[u] for u in found.schools)))
    counts = _scope_counts(session, found)
    if counts["with_data"] == 0:
        held = f"目前只收录了 {counts['programs']} 个项目的名称，" if counts["programs"] else ""
        return "school_not_collected", f"{names}{held}还没有采到官方录取要求，{tail}"
    subject = _subject_label(found)
    if found.narrowing_pattern and counts["fitting"] and not counts["fitting_with_data"]:
        return "no_program_in_field", (
            f"{names}有 {counts['fitting']} 个与{subject}相符的项目，但还没有采到它们的官方录取要求。{tail}"
        )
    if found.fields and counts["in_field_with_data"] == 0:
        pending = (
            f"该方向有 {counts['in_field']} 个项目还没采到要求。" if counts["in_field"]
            else "库里没有这个方向的项目。"
        )
        return "no_program_in_field", (
            f"{names}已收录 {counts['with_data']} 个项目的官方录取要求，但其中没有{subject}方向的，{pending}"
            f"可以换个方向问，或在项目库里查看该校已收录的项目。{tail}"
        )
    return "no_citable_source", "找到了相关项目，但它没有可引用的官方来源链接，所以我不能回答它的要求。已记录为待补来源。"


def gate(session: Session, query: str, ranking: str | None = None) -> dict:
    """Run retrieval and the gate. Returns the state update for the graph.

    `ranking` defaults to ``ADVISOR_RETRIEVAL``; the question is embedded only when the ranking uses
    vectors and a key is configured (otherwise nothing is sent anywhere)."""
    ranking = ranking or settings.advisor_retrieval
    vector = embeddings.embed_query(query) if ranking in ("vector", "hybrid") else None
    found = search_requirements(session, query, ranking=ranking, query_vector=vector)
    strong = [h for h in found.hits if _citable(h.source)]
    signals = {
        "schools": found.schools,
        "fields": found.fields,
        "countries": found.countries,
        "hits": len(found.hits),
        "citable": len(strong),
        "missing_schools": found.missing_schools,
        "subject_fallback": found.subject_fallback,
        "ranking": found.ranking,
        "fts_terms": found.fts_terms,
    }
    if not strong:
        reason, text = refusal(session, found)
        logger.warning("knowledge gap reason=%s query=%r signals=%s", reason, query, signals)
        return {
            "evidence_strong": False,
            "refusal": reason,
            "refusal_text": text,
            "citations": [],
            "trace": {"evidence_gate": "weak", "gate_signals": signals},
        }
    if found.missing_schools:
        logger.warning("knowledge gap reason=partial query=%r signals=%s", query, signals)
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
    lines = [evidence_line(i + 1, h) for i, h in enumerate(strong)]
    if found.subject_fallback:
        lines.append(
            f"（没有找到名称与{_subject_label(found)}相符的项目，以上是同一学科大类的项目；"
            "回答时先说明这一点，不要把它们当成用户问的那个项目）"
        )
    if found.missing_schools:
        missing = _join_names(list(dict.fromkeys(found.school_names[u] for u in found.missing_schools)))
        lines.append(f"（未检索到以下学校的相关官方要求，不要回答它们的要求：{missing}）")
    return {
        "evidence_strong": True,
        "evidence": "\n".join(lines),
        "citations": citations,
        "trace": {"evidence_gate": "strong", "gate_signals": signals},
    }
