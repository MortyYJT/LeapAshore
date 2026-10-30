"""Knowledge gaps: recording the advisor's refusals and reviewing them (openspec/changes/knowledge-gaps).

- `record` adds one refusal to its gap (D1, D2), the asker as a keyed hash (D4); `record_safely` is the
  advisor's entry point and never raises.
- `delete_reports_of`, `rekey_reports` and `sweep_reports` keep the reports to what the privacy rules
  allow (D5).
- `list_gaps`, `show_gap` and `review` are the review, shared by the admin API and the CLI (D6, D7).
"""

import hashlib
import hmac
import logging
import re
import unicodedata
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models.collect import CollectPage, PageState
from app.models.knowledge_gap import KnowledgeGap, KnowledgeGapReport
from app.models.program import University
from app.models.snapshot import SnapshotPage
from app.services.refusals import Refused

logger = logging.getLogger(__name__)

OPEN, RECOLLECT_QUEUED, DISMISSED = "open", "recollect_queued", "dismissed"
STATUSES = (OPEN, RECOLLECT_QUEUED, DISMISSED)
RECOLLECT, DISMISS = "recollect", "dismiss"
QUESTION_CHARS = 500
# Pages a review queues again. Never `blocked` (a refusal is not retried around) or `needs_human`
# (a person has to look); `done`/`unchanged`/`queued` need nothing (D7).
REQUEUE_STATES = (PageState.PENDING, PageState.FAILED, PageState.DEFERRED)
SCHOOL_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")
_HASH_DOMAIN = "knowledge-gap-reporter\n"
_warned_no_key = False


# ---- the key and the asker ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    """Lower case, compatibility forms, spaces and punctuation removed: how two wordings of one thing meet."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(c for c in text if unicodedata.category(c)[0] in "LN")


def gap_key(route: str, reason: str, schools: Iterable[str], fields: Iterable[str], subject_words: Iterable[str],
            topics: Iterable[str], question: str) -> str:
    """The gap a refusal belongs to (D2). The question counts only when no school was recognised."""
    parts = [route, reason, ",".join(sorted(set(schools))), ",".join(sorted(set(fields))),
             ",".join(sorted({_fold(w) for w in subject_words})), ",".join(sorted(set(topics)))]
    if reason == "no_school":
        parts.append(_fold(question)[:QUESTION_CHARS])
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def reporter_hash(subject: str | None) -> str | None:
    """The asker as HMAC-SHA256 of the subject id under `KNOWLEDGE_GAP_HASH_KEY`; None without a key (D4)."""
    global _warned_no_key
    key = settings.knowledge_gap_hash_key
    if not subject:
        return None
    if not key:
        if not _warned_no_key:
            logger.warning("KNOWLEDGE_GAP_HASH_KEY is not set: knowledge-gap reports are stored without an asker")
            _warned_no_key = True
        return None
    return hmac.new(key.encode("utf-8"), (_HASH_DOMAIN + subject).encode("utf-8"), hashlib.sha256).hexdigest()


# ---- recording ---------------------------------------------------------------------------------------------


def record(session: Session, *, route: str, reason: str, question: str, subject: str | None,
           schools: Iterable[str] = (), fields: Iterable[str] = (), subject_words: Iterable[str] = (),
           topics: Iterable[str] = (), now: datetime | None = None) -> str:
    """Add one refusal to its gap, creating the gap on first sight; returns the gap's id. Commits."""
    now = now or datetime.now(UTC)
    schools, fields, words, topics = (sorted(set(schools)), sorted(set(fields)), sorted(set(subject_words)),
                                      sorted(set(topics)))
    statement = insert(KnowledgeGap).values(
        id=str(uuid.uuid4()), gap_key=gap_key(route, reason, schools, fields, words, topics, question),
        route=route, reason=reason, university_ids=schools, fields=fields, subject_words=words, topics=topics,
        report_count=1, first_seen_at=now, last_seen_at=now, status=OPEN,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[KnowledgeGap.gap_key],
        set_={"report_count": KnowledgeGap.report_count + 1,
              "last_seen_at": func.greatest(KnowledgeGap.last_seen_at, statement.excluded.last_seen_at)},
    ).returning(KnowledgeGap.id)
    gap_id = session.execute(statement).scalar_one()
    session.add(KnowledgeGapReport(id=str(uuid.uuid4()), gap_id=gap_id, reporter_hash=reporter_hash(subject),
                                   question=(question or "")[:QUESTION_CHARS], created_at=now))
    session.commit()
    return gap_id


def record_safely(**kwargs) -> str | None:
    """`record` in a session of its own, for the advisor: a failure is logged, never raised (D3)."""
    if not settings.knowledge_gaps_record:
        return None
    try:
        with SessionLocal() as session:
            return record(session, **kwargs)
    except Exception:  # noqa: BLE001 - the applicant's turn must not fail because a report could not be kept
        logger.exception("could not record a knowledge gap (reason=%s)", kwargs.get("reason"))
        return None


# ---- privacy ----------------------------------------------------------------------------------------------


def delete_reports_of(session: Session, subject: str) -> int:
    """Delete a subject's reports (not committed). The gaps keep their counts (D5)."""
    hashed = reporter_hash(subject)
    if hashed is None:
        return 0
    return session.execute(delete(KnowledgeGapReport).where(KnowledgeGapReport.reporter_hash == hashed)).rowcount


def rekey_reports(session: Session, source: str, target: str) -> int:
    """Move an anonymous subject's reports to the account it merged into (not committed)."""
    old, new = reporter_hash(source), reporter_hash(target)
    if old is None or new is None:
        return 0
    return session.execute(update(KnowledgeGapReport).where(KnowledgeGapReport.reporter_hash == old)
                           .values(reporter_hash=new)).rowcount


def sweep_reports(session: Session, apply: bool, now: datetime | None = None) -> dict:
    """Delete reports older than the retention period (D5); the gaps stay."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=settings.knowledge_gap_retention_days)
    old = KnowledgeGapReport.created_at < cutoff
    count = session.scalar(select(func.count()).select_from(KnowledgeGapReport).where(old))
    if apply and count:
        session.execute(delete(KnowledgeGapReport).where(old))
        session.commit()
    return {"old_gap_reports": count}


# ---- reading ----------------------------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _summaries(session: Session, gaps: list[KnowledgeGap]) -> list[dict]:
    if not gaps:
        return []
    ids = [g.id for g in gaps]
    reviewed = {g.id: g.reviewed_at for g in gaps}
    stats = {
        row.gap_id: row for row in session.execute(
            select(KnowledgeGapReport.gap_id,
                   func.count(distinct(KnowledgeGapReport.reporter_hash)).label("askers"),
                   func.count().filter(KnowledgeGapReport.reporter_hash.is_(None)).label("anonymous"))
            .where(KnowledgeGapReport.gap_id.in_(ids)).group_by(KnowledgeGapReport.gap_id))
    }
    since = {gap_id: 0 for gap_id in ids}
    for gap in gaps:
        if gap.reviewed_at is not None:
            since[gap.id] = session.scalar(select(func.count()).select_from(KnowledgeGapReport).where(
                KnowledgeGapReport.gap_id == gap.id, KnowledgeGapReport.created_at > reviewed[gap.id]))
    names = dict(session.execute(select(University.id, University.name).where(
        University.id.in_({u for g in gaps for u in g.university_ids}))).all())
    out = []
    for g in gaps:
        stat = stats.get(g.id)
        # Askers are counted from the reports still kept; with any report stored without an asker
        # (no key configured) the number is unknown, not a smaller one.
        askers = None if stat is not None and stat.anonymous else (stat.askers if stat is not None else 0)
        out.append({
            "id": g.id, "route": g.route, "reason": g.reason,
            "schools": [{"id": u, "name": names.get(u)} for u in g.university_ids],
            "fields": g.fields, "subjectWords": g.subject_words, "topics": g.topics,
            "reports": g.report_count, "askers": askers,
            "firstSeenAt": _iso(g.first_seen_at), "lastSeenAt": _iso(g.last_seen_at),
            "status": g.status, "reviewedAt": _iso(g.reviewed_at), "reviewNote": g.review_note,
            "recollect": g.recollect, "reportsSinceReview": since[g.id],
        })
    return out


def list_gaps(session: Session, status: str = OPEN, limit: int = 100) -> list[dict]:
    """Gaps in `status` (or all with "all"), most reported first."""
    query = select(KnowledgeGap)
    if status != "all":
        query = query.where(KnowledgeGap.status == status)
    query = query.order_by(KnowledgeGap.report_count.desc(), KnowledgeGap.last_seen_at.desc()).limit(limit)
    return _summaries(session, list(session.scalars(query)))


def show_gap(session: Session, gap_id: str, questions: int = 20) -> dict:
    gap = session.get(KnowledgeGap, gap_id)
    if gap is None:
        raise Refused(404, "没有这个知识缺口。")
    out = _summaries(session, [gap])[0]
    out["questions"] = [
        {"question": q, "at": _iso(at)} for q, at in session.execute(
            select(KnowledgeGapReport.question, KnowledgeGapReport.created_at)
            .where(KnowledgeGapReport.gap_id == gap_id)
            .order_by(KnowledgeGapReport.created_at.desc(), KnowledgeGapReport.id).limit(questions))
    ]
    return out


# ---- review ---------------------------------------------------------------------------------------------


def load_schools() -> dict[str, dict]:
    from app.collect.queue import load_schools as from_file

    return from_file()


def school_keys_for(session: Session, university_ids: Iterable[str], schools: dict[str, dict]) -> dict[str, list[str]]:
    """The collection keys of each university (D7): its own id when `_schools.json` has it, else the keys
    its snapshot pages were collected under, else a `_schools.json` row with the same name."""
    out: dict[str, list[str]] = {}
    by_name: dict[str, str] = {}
    for key, row in schools.items():
        for name in (row.get("name_en"), row.get("name_zh")):
            if name:
                by_name.setdefault(_fold(name), key)
    for uid in university_ids:
        if uid in schools:
            out[uid] = [uid]
            continue
        keys = sorted(set(session.scalars(select(SnapshotPage.school_key).where(SnapshotPage.university_id == uid))))
        if not keys:
            row = session.get(University, uid)
            names = [n for n in ((row.name_en, row.name) if row else ()) if n]
            keys = sorted({by_name[_fold(n)] for n in names if _fold(n) in by_name})
        out[uid] = keys
    return out


def send_tasks(page_ids: list[str], discover: list[str], budget_key: str, cap: float) -> None:
    """Hand the work to the collection queue's Celery tasks."""
    from app.worker import discover_task, page_task

    for page_id in page_ids:
        page_task.delay(page_id, budget_key, cap)
    for school_key in discover:
        discover_task.delay(school_key, budget_key, cap)


def review(session: Session, gap_id: str, decision: str, *, reviewer: str | None = None, note: str | None = None,
           school_keys: list[str] | None = None, now: datetime | None = None) -> dict:
    """Dismiss a gap, or queue its schools' re-collection (D7). Returns the gap as `show_gap` does."""
    from app.collect.queue import BEIJING

    now = now or datetime.now(UTC)
    gap = session.get(KnowledgeGap, gap_id, with_for_update=True)
    if gap is None:
        raise Refused(404, "没有这个知识缺口。")
    if decision not in (RECOLLECT, DISMISS):
        raise Refused(422, "decision 只能是 recollect 或 dismiss。")
    if decision == DISMISS:
        gap.status, gap.reviewed_at, gap.reviewed_by, gap.review_note = DISMISSED, now, reviewer, note
        session.commit()
        return show_gap(session, gap_id)

    schools = load_schools()
    if school_keys is not None:
        bad = [k for k in school_keys if not SCHOOL_KEY.match(k)]
        if bad:
            raise Refused(422, f"学校 key 不合法：{'、'.join(bad)}")
        keys = list(dict.fromkeys(school_keys))
        unmapped: list[str] = []
    else:
        mapped = school_keys_for(session, gap.university_ids, schools)
        keys = list(dict.fromkeys(k for uid in gap.university_ids for k in mapped[uid]))
        unmapped = [uid for uid in gap.university_ids if not mapped[uid]]
    plan, page_ids, discover = [], [], []
    for key in keys:
        pages = list(session.scalars(select(CollectPage).where(
            CollectPage.school_key == key, CollectPage.state.in_(REQUEUE_STATES)).with_for_update()))
        listed = bool((schools.get(key) or {}).get("listing_urls"))
        if not pages and not listed:
            continue
        for page in pages:
            page.state = PageState.QUEUED
            page_ids.append(page.id)
        if listed:
            discover.append(key)
        plan.append({"schoolKey": key, "requeued": len(pages), "discovery": listed})
    if not plan:
        session.rollback()
        why = "、".join(keys or unmapped) or "（缺口没有对应的学校）"
        raise Refused(409, f"没有可补采的内容：{why} 没有可重排的页面，也没有列表页。可以指定 schoolKeys，或改为 dismiss。")
    budget_key = f"daily:{now.astimezone(BEIJING).date().isoformat()}"
    gap.status, gap.reviewed_at, gap.reviewed_by, gap.review_note = RECOLLECT_QUEUED, now, reviewer, note
    gap.recollect = {"schools": plan, "unmapped": unmapped, "budget": budget_key}
    session.commit()
    try:
        send_tasks(page_ids, discover, budget_key, settings.collect_daily_budget_cny)
    except Exception as error:  # noqa: BLE001 - the broker is down: the review did not happen
        logger.exception("could not send the re-collection of gap %s", gap_id)
        gap = session.get(KnowledgeGap, gap_id)
        gap.status = OPEN
        gap.review_note = f"{note + '；' if note else ''}任务没发出去（{type(error).__name__}: {str(error)[:200]}）；" \
                          "已排队的页面可用 python -m app.collect.queue resume 重发"
        session.commit()
        raise Refused(503, "补采任务没发出去（采集队列不可用），缺口仍是待审核。") from error
    return show_gap(session, gap_id)


__all__ = ["OPEN", "RECOLLECT_QUEUED", "DISMISSED", "STATUSES", "RECOLLECT", "DISMISS", "QUESTION_CHARS", "gap_key",
           "reporter_hash", "record", "record_safely", "delete_reports_of", "rekey_reports", "sweep_reports",
           "list_gaps", "show_gap", "review", "school_keys_for", "send_tasks", "load_schools"]
