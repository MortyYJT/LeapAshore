"""The admin's verification of an official page (openspec source-verification, TASKS.md P2 #3).

The only writer of a non-null `sources.verified_at`. A person reads, for one page, each program's stored
values with the quotes behind them and the page's snapshot text, and confirms; the confirmation names
the snapshot they read (`content_sha256`), and it is refused when that is not the page's latest version
or when no text of it is stored. The database repeats the rule from the other side: a trigger on
`sources` accepts a new date only in a transaction that recorded an admin's confirmation row for the
same page and moment (alembic c8e1f4a7b2d9).

Read-only apart from `verify` and `revoke`. The values shown are what the catalogue serves; the quotes
come from the version's `body_text` (one `[field] quote (出处: url)` per line, written by the importer)
and from `program_deadlines`.
"""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, selectinload

from app.models.account import Account
from app.models.application import Application
from app.models.program import Program, University
from app.models.snapshot import SnapshotChunk, SnapshotPage
from app.models.source import Source, SourceStatus, SourceVerification, SourceVersion
from app.services.refusals import Refused

NO_SUCH_PAGE = "没有这个页面，或它没有导入过的采集版本。"
ALREADY_VERIFIED = "这个页面已经核验过；要重新核验，先撤销。"
NOT_VERIFIED = "这个页面还没有核验，没有可撤销的。"
VERSION_CHANGED = "页面或它的值在你打开后变了，请刷新后重新阅读。"
NO_SNAPSHOT = "没有这一版的快照正文，不能确认核验。"

STATUSES = ("unverified", "verified", "all")

# The fields shown, in order, with the `body_text` names their quotes carry.
FIELDS = (
    ("english", "英语要求", ("ielts", "toefl")),
    ("academic", "学术要求", ("academic",)),
    ("china", "中国学生均分", ("china_requirement",)),
    ("prerequisites", "先修课", ("prerequisites",)),
    ("deadlines", "截止日期", ("deadlines",)),
)

_LINE = re.compile(r"^\[([a-z_]+)\] (.*)$")
_CITED = re.compile(r"^(.*) \(出处: (.+)\)$", re.DOTALL)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _number(value: Decimal) -> str:
    return f"{value.normalize():f}"


def parse_quotes(body: str | None) -> dict[str, list[dict]]:
    """The version's quotes by field name. A line without a `[field]` prefix continues the quote above."""
    out: dict[str, list[dict]] = {}
    last: dict | None = None
    for line in (body or "").splitlines():
        match = _LINE.match(line)
        if match is None:
            if last is not None:
                last["text"] += "\n" + line
            continue
        last = {"text": match.group(2), "sourceUrl": None}
        out.setdefault(match.group(1), []).append(last)
    for quotes in out.values():
        for quote in quotes:
            cited = _CITED.match(quote["text"])
            if cited:
                quote["text"], quote["sourceUrl"] = cited.group(1), cited.group(2)
    return out


def _latest_version(session: Session, source_id: str) -> SourceVersion | None:
    return session.scalar(select(SourceVersion).where(SourceVersion.source_id == source_id)
                          .order_by(SourceVersion.version_no.desc()).limit(1))


def _snapshot_ready(session: Session, url: str, sha: str) -> bool:
    return session.scalar(select(func.count()).select_from(SnapshotChunk).join(SnapshotPage)
                          .where(SnapshotPage.url == url, SnapshotPage.snapshot_sha256 == sha)) > 0


def _fields(program: Program, quotes: dict[str, list[dict]], own_url: str) -> list[dict]:
    values: dict[str, list[str]] = {
        "english": [program.english_requirement] if program.english_requirement else [],
        "academic": [program.academic_requirement] if program.academic_requirement else [],
        "china": ([f"211 院校均分 {_number(program.minimum_mark)}"] if program.minimum_mark is not None else [])
        + ([f"其他院校均分 {_number(program.non_211_minimum_mark)}"] if program.non_211_minimum_mark is not None else []),
        "prerequisites": [p.label for p in program.prerequisites],
        "deadlines": [f"{d.label}：{d.deadline.isoformat()}" if d.label else d.deadline.isoformat()
                      for d in program.deadlines],
    }
    out = []
    for key, label, names in FIELDS:
        found = [q for name in names for q in quotes.get(name, [])]
        if key == "deadlines":
            # A deadline row keeps its own quote; the version's lines add any whose summary was not imported.
            stored = [{"text": d.quote, "sourceUrl": d.source_url} for d in program.deadlines]
            found = stored + [q for q in found if q["text"] not in {s["text"] for s in stored}]
        found = [{**q, "sourceUrl": None if q["sourceUrl"] == own_url else q["sourceUrl"]} for q in found]
        if values[key] or found:
            out.append({"key": key, "label": label, "values": values[key], "quotes": found})
    return out


def _pages(session: Session, own_url: str, programs: list[dict], programs_rows: list[Program], sha: str) -> list[dict]:
    urls = [own_url]
    cited = [q["sourceUrl"] for p in programs for f in p["fields"] for q in f["quotes"]]
    cited += [row.academic_source_url for row in programs_rows]
    for url in cited:
        if url and url.startswith("http") and url not in urls:
            urls.append(url)
    stored = {row.url: row for row in session.scalars(select(SnapshotPage).where(SnapshotPage.url.in_(urls)))}
    chunks: dict[str, list[str]] = {}
    if stored:
        for page_id, chunk in session.execute(
                select(SnapshotChunk.page_id, SnapshotChunk.text)
                .where(SnapshotChunk.page_id.in_([row.id for row in stored.values()]))
                .order_by(SnapshotChunk.page_id, SnapshotChunk.ordinal)):
            chunks.setdefault(page_id, []).append(chunk)
    out = []
    for url in urls:
        row = stored.get(url)
        own = url == own_url
        out.append({
            "url": url, "own": own, "title": row.title if row else None,
            "snapshotSha256": row.snapshot_sha256 if row else None, "fetchedAt": _iso(row.fetched_at) if row else None,
            "matchesVersion": (row is not None and row.snapshot_sha256 == sha) if own else None,
            "text": "\n".join(chunks.get(row.id, [])) if row else None,
        })
    return out


def _history(session: Session, source_id: str) -> list[dict]:
    rows = session.execute(
        select(SourceVerification, Account.email).outerjoin(Account, Account.id == SourceVerification.account_id)
        .where(SourceVerification.source_id == source_id)
        .order_by(SourceVerification.decided_at.desc(), SourceVerification.id))
    return [{"action": v.action, "at": _iso(v.decided_at), "by": email, "contentSha256": v.content_sha256}
            for v, email in rows]


def _programs(session: Session, source: Source, version: SourceVersion) -> tuple[list[Program], list[dict]]:
    rows = list(session.scalars(
        select(Program).where(Program.source_id == source.id)
        .options(selectinload(Program.university), selectinload(Program.prerequisites),
                 selectinload(Program.deadlines))
        .order_by(Program.name_en, Program.id)
        .execution_options(populate_existing=True)))
    quotes = parse_quotes(version.body_text)
    return rows, [{
        "id": p.id, "name": p.name, "nameEn": p.name_en, "school": p.university.name if p.university else None,
        "dataStatus": p.data_status, "fields": _fields(p, quotes, source.url),
    } for p in rows]


def _digest(version: SourceVersion, programs: list[dict]) -> str:
    """What the admin was shown: the snapshot and every value and quote. A confirmation names it, so a
    re-import that changed a value while they read (same snapshot) is refused rather than confirmed."""
    shown = json.dumps({"sha": version.content_sha256, "programs": programs}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(shown.encode("utf-8")).hexdigest()


def detail(session: Session, source_id: str) -> dict:
    source = session.get(Source, source_id)
    version = _latest_version(session, source_id) if source else None
    if source is None or version is None:
        raise Refused(404, NO_SUCH_PAGE)
    rows, programs = _programs(session, source, version)
    pages = _pages(session, source.url, programs, rows, version.content_sha256)
    ready = bool(pages[0]["matchesVersion"] and pages[0]["text"])
    return {
        "source": {"id": source.id, "url": source.url, "title": source.title, "status": source.status,
                   "verifiedAt": _iso(source.verified_at)},
        "version": {"versionNo": version.version_no, "contentSha256": version.content_sha256,
                    "fetchedAt": _iso(version.fetched_at)},
        "programs": programs,
        "pages": pages,
        "canVerify": source.verified_at is None and ready,
        "digest": _digest(version, programs),
        "history": _history(session, source_id),
    }


def list_pages(session: Session, status: str = "unverified", q: str | None = None, limit: int = 50,
               offset: int = 0) -> dict:
    """Pages that back imported programs; the ones applicants put in a portfolio first, then by school."""
    per_source = (
        select(Program.source_id.label("source_id"), func.count(Application.id).label("uses"),
               func.min(University.name).label("school"))
        .join(University, University.id == Program.university_id)
        .outerjoin(Application, Application.program_id == Program.id)
        .group_by(Program.source_id).subquery())
    conditions = [Source.id.in_(select(SourceVersion.source_id))]
    if status == "unverified":
        conditions.append(Source.verified_at.is_(None))
    elif status == "verified":
        conditions.append(Source.verified_at.is_not(None))
    if q and q.strip():
        term = f"%{q.strip()}%"
        matching = (select(Program.source_id).join(University, University.id == Program.university_id)
                    .where(or_(Program.name.ilike(term), Program.name_en.ilike(term),
                               University.name.ilike(term), University.name_en.ilike(term))))
        conditions.append(or_(Source.url.ilike(term), Source.title.ilike(term), Source.id.in_(matching)))
    base = select(Source, per_source.c.uses, per_source.c.school).join(per_source, per_source.c.source_id == Source.id)
    total = session.scalar(select(func.count()).select_from(base.where(*conditions).subquery()))
    rows = session.execute(base.where(*conditions)
                           .order_by(per_source.c.uses.desc(), per_source.c.school, Source.title, Source.id)
                           .limit(limit).offset(offset)).all()
    ids = [row.Source.id for row in rows]
    programs: dict[str, list[dict]] = {}
    for p in session.scalars(select(Program).where(Program.source_id.in_(ids)).order_by(Program.name_en, Program.id)):
        programs.setdefault(p.source_id, []).append(
            {"id": p.id, "name": p.name, "nameEn": p.name_en, "dataStatus": p.data_status})
    latest = {sid: (sha, at) for sid, sha, at in session.execute(
        select(SourceVersion.source_id, SourceVersion.content_sha256, SourceVersion.fetched_at)
        .where(SourceVersion.source_id.in_(ids))
        .ext(distinct_on(SourceVersion.source_id)).order_by(SourceVersion.source_id, SourceVersion.version_no.desc()))}
    readable = set(session.execute(
        select(SnapshotPage.url, SnapshotPage.snapshot_sha256)
        .where(SnapshotPage.url.in_([row.Source.url for row in rows]), SnapshotPage.chunk_count > 0)).all())
    items = [{
        "sourceId": row.Source.id, "url": row.Source.url, "title": row.Source.title, "school": row.school,
        "status": row.Source.status, "verifiedAt": _iso(row.Source.verified_at), "inPortfolios": row.uses,
        "fetchedAt": _iso(latest[row.Source.id][1]), "programs": programs.get(row.Source.id, []),
        "snapshotReady": (row.Source.url, latest[row.Source.id][0]) in readable,
    } for row in rows]
    return {"items": items, "total": total or 0}


def _locked(session: Session, source_id: str) -> tuple[Source, SourceVersion]:
    """The page, locked for this transaction, so two admins cannot both confirm it."""
    source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    version = _latest_version(session, source_id) if source else None
    if source is None or version is None:
        session.rollback()
        raise Refused(404, NO_SUCH_PAGE)
    return source, version


def verify(session: Session, source_id: str, content_sha256: str, digest: str, account: Account) -> dict:
    """Confirm the page at the version the admin read. Writes `verified_at` and who and when.

    `digest` is the reading view's: under the page's lock (which the importer takes too) the view is
    rebuilt, and anything that changed since the admin opened it refuses the confirmation."""
    source, version = _locked(session, source_id)
    refusal = None
    if source.verified_at is not None:
        refusal = Refused(409, ALREADY_VERIFIED)
    elif version.content_sha256 != content_sha256 or _digest(version, _programs(session, source, version)[1]) != digest:
        refusal = Refused(409, VERSION_CHANGED)
    elif not _snapshot_ready(session, source.url, content_sha256):
        refusal = Refused(409, NO_SNAPSHOT)
    if refusal is not None:
        session.rollback()
        raise refusal
    moment = datetime.now(UTC)
    session.add(SourceVerification(id=str(uuid.uuid4()), source_id=source.id, action="verify",
                                   content_sha256=content_sha256, account_id=account.id, decided_at=moment))
    # The row has to be in the database before the page's date: the trigger looks for it.
    session.flush()
    source.status = SourceStatus.VERIFIED
    source.verified_at = moment
    session.commit()
    return detail(session, source_id)


def revoke(session: Session, source_id: str, account: Account) -> dict:
    """Withdraw a confirmation: the page is 待核验 again; the history keeps both rows."""
    source, version = _locked(session, source_id)
    if source.verified_at is None:
        session.rollback()
        raise Refused(409, NOT_VERIFIED)
    session.add(SourceVerification(id=str(uuid.uuid4()), source_id=source.id, action="revoke",
                                   content_sha256=version.content_sha256, account_id=account.id,
                                   decided_at=datetime.now(UTC)))
    source.status = SourceStatus.UNVERIFIED
    source.verified_at = None
    session.commit()
    return detail(session, source_id)
