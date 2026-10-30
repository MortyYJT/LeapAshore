"""The collection queue: one task per official page (openspec/changes/collect-queue).

    python -m app.collect.queue status
    python -m app.collect.queue discover <school_key>... [--budget backfill --cap 100] [--sync]
    python -m app.collect.queue enqueue [--school K]... [--state pending,failed] [--budget backfill --cap 100]
    python -m app.collect.queue resume [--budget backfill --cap 100]
    python -m app.collect.queue export [--school K]... [--out DIR]

A page goes snapshot (robots.txt, the shared per-host token bucket, refusals recorded) → dedupe by the
HTML and visible-text sha256 → extraction with the advisor's model → `verify`. What it learned is kept in
`collect_pages`; what changed since the page's last verified values is written to
`requirement_changes`. Nothing here writes the catalogue or `verified_at`: `export` merges the results
into the requirement files, which are reviewed, committed and imported as before (D8).

The functions here take their collaborators (fetch, extract, budget) as arguments so the tests can run
them without a network or a model; `app.worker` wires the real ones into Celery tasks.
"""

import argparse
import hashlib
import http.client
import json
import logging
import random
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collect.changes import diff_fields, has_verified_value
from app.collect.extract import ExtractResult, extract_snapshot
from app.collect.faithful import cost_cny
from app.collect.ratelimit import RetryLater
from app.collect.snapshot import SNAPSHOT_ROOT, Blocked, HttpError, snapshot
from app.collect.text import normalize
from app.collect.tidy import heading_of, program_name, tidy_file
from app.collect.verify import (
    LIST_FIELDS,
    MACHINE_CHECKED,
    NEEDS_HUMAN,
    SUMMARY_CHECK,
    SUMMARY_SHA,
    program_status,
    summary_digest,
    summary_verdict,
)
from app.config import settings
from app.models.collect import CollectPage, PageState, RequirementChange

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "requirements"
log = logging.getLogger(__name__)
NAMESPACE = uuid.UUID("0b8f3c52-6a1d-4c3e-9a57-5d2f1e7c4b90")
BEIJING = ZoneInfo("Asia/Shanghai")
BACKFILL_BUDGET = "backfill"
MAX_RETRIES = 4
BACKOFF_BASE = 60
BACKOFF_CAP = 3600
COLLECTOR = "leapashore-queue"
# Visible text shorter than this usually means the page needs its scripts run (measured: a Sydney course
# page is 685 characters plain, 6,269 rendered).
THIN_PAGE_CHARS = 1500
# `last_error` of a page whose render waits for its host's Crawl-delay, then the plain fetch's sha256.
RENDER_PENDING = "render waits for the host's Crawl-delay; plain fetch "
ITEM_KEYS = ("label", "date", "text", "overall", "min_band", "min_mark_211", "min_mark_other", "recommended",
             "scale_note", "quote", "source_sha256", "source_url", "check", "summary_check", "summary_sha")
PROGRAM_KEYS = ("cricos_code", "snapshot_sha256", "fetched_at", "rendered", "collector", "fields", "status")
# A page is not refetched while it is in one of these states unless asked to re-collect.
SETTLED = {PageState.DONE, PageState.UNCHANGED, PageState.BLOCKED, PageState.FAILED, PageState.NEEDS_HUMAN}


class Transient(Exception):
    """A failure that says nothing about the page (timeout, reset, 5xx, model transport): retry later."""


# --- Money -------------------------------------------------------------------------------------------


class Budget:
    """Model spend under one key (D10), shared by every worker through Redis."""

    def __init__(self, client: redis.Redis, key: str, cap_cny: float) -> None:
        self.client = client
        self.key = f"{settings.limits_key_prefix}collect:spent:{key}"
        self.name = key
        self.cap = cap_cny

    def spent(self) -> float:
        return float(self.client.get(self.key) or 0)

    def allows(self) -> bool:
        return self.spent() < self.cap

    def add(self, cny: float) -> None:
        if cny > 0:
            self.client.incrbyfloat(self.key, cny)
            # A daily key is not needed once its day is over; a run key is kept until removed.
            if self.name.startswith("daily:"):
                self.client.expire(self.key, 3 * 24 * 3600)


def daily_budget(client: redis.Redis, now: datetime | None = None) -> Budget:
    day = (now or datetime.now(UTC)).astimezone(BEIJING).date().isoformat()
    return Budget(client, f"daily:{day}", settings.collect_daily_budget_cny)


def backoff_delay(retries: int, rand=random.random) -> float:
    """Seconds before retry number `retries + 1`: 60 s doubling, capped at an hour, jittered to 50–100%."""
    base = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** retries)
    return base * (0.5 + rand() / 2)


# --- Schools and pages -------------------------------------------------------------------------------


def load_schools(data_dir: Path = DATA_DIR) -> dict[str, dict]:
    path = data_dir / "_schools.json"
    return {row["school_key"]: row for row in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}


def school_info(school_key: str, data_dir: Path = DATA_DIR) -> dict:
    row = load_schools(data_dir).get(school_key)
    if row:
        return {"name": row["name_en"], "country": row.get("country"), "listing_urls": row.get("listing_urls") or []}
    path = data_dir / f"{school_key}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"name": data["school_name_en"], "country": data.get("country"),
                "listing_urls": data.get("listing_urls") or []}
    raise KeyError(f"unknown school {school_key!r}")


def page_id_for(school_key: str, url: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{school_key}\n{url}"))


def upsert_page(session: Session, school_key: str, url: str, name: str, *, cricos_code: str | None = None,
                render: bool = False, origin: str = "discovered", state: str = PageState.PENDING,
                fetched_at: datetime | None = None) -> CollectPage:
    """The page's row, created when new. An existing row keeps its state and results."""
    page = session.get(CollectPage, page_id_for(school_key, url))
    if page is None:
        page = CollectPage(id=page_id_for(school_key, url), school_key=school_key, url=url, program_name=name,
                           cricos_code=cricos_code, render=render, origin=origin, state=state, attempts=0,
                           cost_cny=Decimal("0"), fetched_at=fetched_at)
        session.add(page)
        session.flush()
    return page


def file_program(school_key: str, url: str, data_dir: Path = DATA_DIR) -> dict | None:
    """The committed requirement file's program for this page, if any (the first one on that URL)."""
    path = data_dir / f"{school_key}.json"
    if not path.exists():
        return None
    programs = json.loads(path.read_text(encoding="utf-8")).get("programs", [])
    return next((p for p in programs if p.get("url") == url), None)


def _normalized_text(school_key: str, sha: str | None, root: Path) -> str | None:
    path = root / school_key / f"{sha}.txt" if sha else None
    return normalize(path.read_text(encoding="utf-8")) if path is not None and path.exists() else None


def text_sha(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _snapshot_text_sha(school_key: str, sha: str | None, root: Path) -> str | None:
    if not sha:
        return None
    path = root / school_key / f"{sha}.txt"
    return text_sha(path.read_text(encoding="utf-8")) if path.exists() else None


def prior_state(page: CollectPage, data_dir: Path, root: Path) -> tuple[str | None, str | None, dict | None]:
    """(HTML sha256, text sha256, fields) the page had before, from the queue's own last result or,
    for a page the queue has not collected yet, from the committed requirement file (D6)."""
    if page.result is not None or page.snapshot_sha256:
        fields = (page.result or {}).get("fields")
        if page.result is None:
            program = file_program(page.school_key, page.url, data_dir)
            fields = program.get("fields") if program else None
        return page.snapshot_sha256, page.text_sha256, fields
    program = file_program(page.school_key, page.url, data_dir)
    if program is None:
        return None, None, None
    sha = program.get("snapshot_sha256")
    return sha, _snapshot_text_sha(page.school_key, sha, root), program.get("fields")


# --- One page ----------------------------------------------------------------------------------------


def _unanswered(blocked: Blocked) -> bool:
    """A keep-out the site did not state: robots.txt timed out or answered 5xx. The snapshot tool asks
    again after an hour, so this is a failure to retry, not a refusal (D4)."""
    text = str(blocked)
    return "robots.txt itself: no answer" in text or "robots.txt itself: HTTP 5" in text


def _name_from_heading(page: CollectPage, html_path: Path) -> None:
    """A discovered page is named by its link's text; when that text names no degree ("Learn more"),
    the page's own first heading is used instead, if it does. A link text that carries more than the
    name (a card's description, a bare course code) is cut back to the heading (`tidy.program_name`)."""
    from app.collect.discover import HINT, page_heading
    from app.collect.tidy import program_name

    if not html_path.exists():
        return
    heading = page_heading(html_path.read_text(encoding="utf-8"))
    name = program_name(page.program_name, heading)
    if not HINT.search(name) and heading and HINT.search(heading):
        name = heading
    page.program_name = name


def _settle(session: Session, page: CollectPage, state: str, error: str | None = None) -> str:
    page.state = state
    page.last_error = error
    session.commit()
    return state


def collect_page(session: Session, page_id: str, *, budget: Budget, fetch=snapshot, extract=extract_snapshot,
                 root: Path = SNAPSHOT_ROOT, data_dir: Path = DATA_DIR, can_render: bool | None = None,
                 now=lambda: datetime.now(UTC)) -> str:
    """Collect one page and return its new state. Raises `Transient` for a failure worth retrying and
    lets `ratelimit.RetryLater` through (the host's turn is far away; the task re-schedules itself)."""
    page = session.get(CollectPage, page_id)
    if page is None:
        return "missing"
    can_render = settings.collect_can_render if can_render is None else can_render
    if page.render and not can_render:
        page.fetched_at = now()  # attempted: not due again for a re-collection period
        return _settle(session, page, PageState.DEFERRED, "needs a rendered fetch; this host cannot render")
    if not budget.allows():
        return _settle(session, page, PageState.DEFERRED, f"budget {budget.name} reached ({budget.cap} CNY)")
    school = school_info(page.school_key, data_dir)
    page.attempts += 1
    # The last attempt, whatever its outcome: a refused page is not due again the next day.
    previous_attempt, page.fetched_at = page.fetched_at, now()

    pending = page.last_error or ""
    plain = pending[len(RENDER_PENDING):] if page.render and pending.startswith(RENDER_PENDING) else None
    plain_meta_path = root / page.school_key / f"{plain}.json" if plain else None
    render_failed = False
    try:
        meta = fetch(page.url, page.school_key, render=page.render, root=root)
    except Blocked as blocked:
        if _unanswered(blocked):
            page.last_error = str(blocked)[:500]
            session.commit()
            raise Transient(page.last_error) from blocked
        return _settle(session, page, PageState.BLOCKED, str(blocked)[:500])
    except RetryLater:
        raise
    except Exception as error:  # noqa: BLE001 - sorted below; anything unexpected is raised again
        if plain_meta_path is not None and plain_meta_path.exists():
            # The render this page waited a Crawl-delay for failed, however it failed (a Chrome
            # timeout is a subprocess error, an empty render an HttpError): the plain fetch it already
            # has stands, as when a render fails on the first try.
            meta = json.loads(plain_meta_path.read_text(encoding="utf-8"))
            page.render, render_failed = False, True
        elif isinstance(error, HttpError):
            if error.status >= 500:
                page.last_error = str(error)
                session.commit()
                raise Transient(str(error)) from error
            return _settle(session, page, PageState.FAILED, str(error))
        elif isinstance(error, (OSError, TimeoutError, RuntimeError, http.client.HTTPException)):
            # URLError, resets and socket timeouts are OSErrors; a cut-off body is an HTTPException; a
            # failed render is a RuntimeError.
            page.last_error = f"{type(error).__name__}: {str(error)[:300]}"
            session.commit()
            raise Transient(page.last_error) from error
        else:
            raise

    if not page.render and not can_render and (meta.get("text_chars") or 0) < THIN_PAGE_CHARS:
        # Too thin to be the page a reader sees, and this host cannot run its scripts: no model call
        # on a shell page; a machine with Chrome collects it.
        page.render = True
        return _settle(session, page, PageState.DEFERRED, "the page needs rendering; this host cannot render")
    if not page.render and can_render and not render_failed and (meta.get("text_chars") or 0) < THIN_PAGE_CHARS:
        # A page built by JavaScript shows next to nothing without its scripts: render it once, and
        # from then on (the agents' brief did the same by hand).
        try:
            meta = fetch(page.url, page.school_key, render=True, root=root)
            page.render = True
        except Blocked as blocked:
            return _settle(session, page, PageState.BLOCKED, str(blocked)[:500])
        except RetryLater:
            # The host's turn (its Crawl-delay) is far away. Remember that the page needs rendering,
            # so the rescheduled task goes straight to the render instead of spending the host's
            # turn on the plain fetch again and waiting a whole Crawl-delay once more, forever.
            page.render = True
            page.fetched_at = previous_attempt
            page.last_error = f"{RENDER_PENDING}{meta['sha256']}"
            session.commit()
            raise
        except Exception:  # noqa: BLE001 - a failed render: the plain fetch still stands
            pass
    sha = meta["sha256"]
    if page.origin == "discovered":
        from app.collect.tidy import not_a_program

        if page.result is None:
            _name_from_heading(page, root / page.school_key / f"{sha}.html")
        name = program_name(page.program_name, heading_of(root, page.school_key, sha))
        reason = not_a_program(name, page.url, school.get("listing_urls") or [])
        if reason:
            # No model call on a page that is not one program, on the first visit or a later one.
            return _settle(session, page, PageState.FAILED, reason)
    new_text_sha = _snapshot_text_sha(page.school_key, sha, root)
    old_sha, old_text_sha, old_fields = prior_state(page, data_dir, root)
    if sha == old_sha or (old_text_sha is not None and new_text_sha == old_text_sha):
        # The page says what it said: no model call, nothing changed (D6).
        page.snapshot_sha256, page.text_sha256 = sha, new_text_sha
        _settle(session, page, PageState.UNCHANGED)
        refresh_chunks(session, page, root)
        return PageState.UNCHANGED
    if not budget.allows():
        # Not extracted, so not collected: due again as soon as there is money, not in a month.
        page.fetched_at = previous_attempt
        return _settle(session, page, PageState.DEFERRED, f"budget {budget.name} reached ({budget.cap} CNY)")

    try:
        result: ExtractResult = extract(page.school_key, sha, program_name=page.program_name,
                                        school_name=school["name"], country=school["country"], url=page.url, root=root)
    except Exception as error:  # noqa: BLE001 - the model's transport (timeouts, 5xx, rate limits)
        page.last_error = f"model: {type(error).__name__}: {str(error)[:300]}"
        session.commit()
        raise Transient(page.last_error) from error

    spent = cost_cny(result.usage)
    budget.add(spent)
    page.cost_cny = (page.cost_cny or Decimal("0")) + Decimal(str(round(spent, 6)))
    page.model = result.model
    page.extracted_at = now()
    program = dict(result.program)
    if page.cricos_code:
        program["cricos_code"] = page.cricos_code
    program["fetched_at"] = meta.get("fetched_at")
    if page.render:
        program["rendered"] = True
    page.rejected = result.rejected or None

    if result.error:
        # The answer says nothing about the page; the last good result stays the page's result.
        return _settle(session, page, PageState.NEEDS_HUMAN, result.error)
    if has_verified_value(old_fields) and not has_verified_value(program.get("fields")):
        # A page that lost every value is more likely a broken fetch (a challenge page, a failed
        # render) than a programme that dropped all its requirements: a person looks, nothing is
        # recorded as removed, and the earlier result stays the one exported.
        return _settle(session, page, PageState.NEEDS_HUMAN, "the page kept no verified value; it had some before")

    if old_fields is not None:
        old_text, new_text = _normalized_text(page.school_key, old_sha, root), _normalized_text(page.school_key, sha, root)
        for change in diff_fields(old_fields, program.get("fields"), old_text, new_text):
            session.add(RequirementChange(
                id=str(uuid.uuid4()), page_id=page.id, school_key=page.school_key, url=page.url,
                program_name=page.program_name, field=change["field"], kind=change["kind"],
                old_value=change["old"], new_value=change["new"], old_sha256=old_sha, new_sha256=sha,
            ))
    page.result = program
    page.snapshot_sha256, page.text_sha256 = sha, new_text_sha
    _settle(session, page, PageState.DONE)
    refresh_chunks(session, page, root)
    return PageState.DONE


def refresh_chunks(session: Session, page: CollectPage, root: Path = SNAPSHOT_ROOT) -> str:
    """Re-cut the advisor's chunks of a page the queue has just collected (openspec snapshot-rag D5).

    Best effort, after the page's own state is committed: a failure here is logged and leaves the page
    collected; the next `python -m app.collect.chunks ingest` catches up."""
    from app.collect import chunks

    try:
        return chunks.refresh_page(session, page.school_key, page.url, page.snapshot_sha256, root)
    except Exception:  # noqa: BLE001 - the advisor's copy must not fail the collection
        session.rollback()
        log.exception("could not refresh the chunks of %s", page.url)
        return "error"


# --- Many pages --------------------------------------------------------------------------------------


def interleave(pages: list[CollectPage]) -> list[CollectPage]:
    """Round-robin over schools, so concurrent workers spread over hosts instead of queueing on one."""
    by_school: dict[str, list[CollectPage]] = {}
    for page in pages:
        by_school.setdefault(page.school_key, []).append(page)
    out, queues = [], list(by_school.values())
    while queues:
        queues = [q for q in queues if q]
        for q in queues:
            out.append(q.pop(0))
    return out


def mark_queued(session: Session, pages: list[CollectPage]) -> list[str]:
    ordered = interleave(pages)
    for page in ordered:
        page.state = PageState.QUEUED
    session.commit()
    return [page.id for page in ordered]


def seed_from_files(session: Session, data_dir: Path = DATA_DIR) -> int:
    """A row for every program a committed file lists, so the beat can re-collect it. New rows only."""
    added = 0
    known = set(session.scalars(select(CollectPage.id)))
    for path in sorted(p for p in data_dir.glob("*.json") if not p.name.startswith("_")):
        data = json.loads(path.read_text(encoding="utf-8"))
        collected = data.get("collected_at")
        for program in data.get("programs", []):
            pid = page_id_for(data["school_key"], program["url"])
            if pid in known:
                continue
            known.add(pid)
            when = program.get("fetched_at") or collected
            fetched = datetime.fromisoformat(when) if when else None
            if fetched is not None and fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=UTC)
            meta = SNAPSHOT_ROOT / data["school_key"] / f"{program.get('snapshot_sha256')}.json"
            rendered = bool(program.get("rendered")) or (
                meta.exists() and bool(json.loads(meta.read_text(encoding="utf-8")).get("rendered")))
            upsert_page(session, data["school_key"], program["url"], program["name"],
                        cricos_code=program.get("cricos_code"), render=rendered,
                        origin="file", state=PageState.UNCHANGED, fetched_at=fetched)
            added += 1
    session.commit()
    return added


def due_pages(session: Session, now: datetime, limit: int) -> list[CollectPage]:
    """Settled pages not fetched for `COLLECT_RECOLLECT_DAYS`, oldest first. Blocked pages wait for
    their refusal to expire like any other page: the snapshot tool decides whether the host may be asked."""
    cutoff = now - timedelta(days=settings.collect_recollect_days)
    return list(session.scalars(
        select(CollectPage)
        .where(CollectPage.state.in_([PageState.DONE, PageState.UNCHANGED, PageState.BLOCKED,
                                      PageState.FAILED, PageState.DEFERRED, PageState.NEEDS_HUMAN]))
        .where((CollectPage.fetched_at.is_(None)) | (CollectPage.fetched_at < cutoff))
        .order_by(CollectPage.fetched_at.asc().nulls_first())
        .limit(limit)
    ))


# --- Export ------------------------------------------------------------------------------------------


def _ordered(item: dict) -> dict:
    out = {key: item[key] for key in ITEM_KEYS if key in item}
    out.update({k: v for k, v in item.items() if k not in out})
    return out


def _carry_summary_verdicts(old: dict, new: dict) -> None:
    """Keep the summary check's verdict for every value the new result states exactly as before.

    A page the queue collected before the check (or found unchanged) has a result without verdicts;
    replacing the file's program with it must not quietly make a downgraded summary usable again.
    """
    judged = {}
    for name, value in (old.get("fields") or {}).items():
        for item in value if name in LIST_FIELDS else [value]:
            if summary_verdict(item) is not None:
                judged[(name, summary_digest(item))] = (item[SUMMARY_CHECK], item[SUMMARY_SHA])
    if not judged:
        return
    for name, value in (new.get("fields") or {}).items():
        for item in value if name in LIST_FIELDS else [value]:
            if summary_verdict(item) is None and (name, summary_digest(item)) in judged:
                item[SUMMARY_CHECK], item[SUMMARY_SHA] = judged[(name, summary_digest(item))]
    new["status"] = program_status(new)


def export_school(session: Session, school_key: str, data_dir: Path = DATA_DIR, out_dir: Path | None = None,
                  today: date | None = None, root: Path = SNAPSHOT_ROOT) -> dict:
    """Merge the queue's results for one school into its requirement file (D8).

    A collected program replaces the file's program with the same URL and name, else the only one on
    that URL, else it is appended; programs the queue did not collect are kept as they are. A page's
    result is its last good one: an unusable answer or a page that lost every value does not replace it.
    """
    out_dir = out_dir or data_dir
    # Every page with a result: a later `unchanged` or `needs_human` keeps the last good result (D8).
    pages = list(session.scalars(select(CollectPage).where(
        CollectPage.school_key == school_key, CollectPage.result.is_not(None))
        .order_by(CollectPage.created_at, CollectPage.url)))
    path = data_dir / f"{school_key}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        school = load_schools(data_dir).get(school_key) or {}
        data = {"school_key": school_key, "school_name_en": school.get("name_en") or school_key,
                "country": school.get("country"), "collector": COLLECTOR,
                "collected_at": (today or date.today()).isoformat(),
                "listing_urls": school.get("listing_urls") or [], "complete": False, "programs": []}
    programs = data.setdefault("programs", [])
    replaced = added = 0
    for page in pages:
        result = dict(page.result)
        result.setdefault("collector", f"{COLLECTOR} ({page.model or 'model'})")
        # The database hands JSON back with its keys sorted; write them in the files' usual order.
        program = {"name": page.program_name, "url": page.url}
        for key in PROGRAM_KEYS:
            if key in result:
                program[key] = result[key]
        program.update({k: v for k, v in result.items() if k not in program})
        program["fields"] = {name: ([_ordered(i) for i in value] if isinstance(value, list) else _ordered(value))
                             for name, value in (program.get("fields") or {}).items()}
        same = [i for i, p in enumerate(programs) if p.get("url") == page.url]
        # The file may hold the name `tidy` gave it rather than the row's link text.
        tidied = program_name(page.program_name, heading_of(root, school_key, result.get("snapshot_sha256")))
        named = [i for i in same if programs[i].get("name") in (page.program_name, tidied)]
        target = named[0] if named else (same[0] if len(same) == 1 else None)
        if target is None:
            programs.append(program)
            added += 1
        else:
            _carry_summary_verdicts(programs[target], program)
            programs[target] = program
            replaced += 1
    # The same rules as `python -m app.collect.tidy`, so an export does not undo a tidied file.
    data, _ = tidy_file(data, load_schools(data_dir).get(school_key), root=root)
    programs = data["programs"]
    summary = {"programs": len(programs), MACHINE_CHECKED: 0, NEEDS_HUMAN: 0}
    for program in programs:
        summary[MACHINE_CHECKED if program.get("status") == MACHINE_CHECKED else NEEDS_HUMAN] += 1
    data["verification"] = summary
    if pages:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{school_key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                                                     encoding="utf-8")
    return {"school": school_key, "replaced": replaced, "added": added, "programs": len(programs)}


# --- Command line ------------------------------------------------------------------------------------


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, socket_timeout=5, socket_connect_timeout=5)


def status(session: Session, budget_keys: list[str]) -> dict:
    counts = dict(session.execute(select(CollectPage.state, func.count()).group_by(CollectPage.state)).all())
    schools = dict(session.execute(select(CollectPage.state, func.count(func.distinct(CollectPage.school_key)))
                                   .group_by(CollectPage.state)).all())
    spent = session.scalar(select(func.coalesce(func.sum(CollectPage.cost_cny), 0)))
    client = redis_client()
    return {
        "pages": counts, "schools_by_state": schools, "cost_cny_recorded": float(spent),
        "budgets": {key: Budget(client, key, 0).spent() for key in budget_keys},
        "changes": session.scalar(select(func.count()).select_from(RequirementChange)),
    }


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("enqueue", "resume", "discover"):
        p = sub.add_parser(name)
        p.add_argument("--budget", default=BACKFILL_BUDGET)
        p.add_argument("--cap", type=float, default=100.0, help="CNY for this budget key")
        if name == "enqueue":
            p.add_argument("--school", action="append")
            p.add_argument("--state", default="pending")
        if name == "discover":
            p.add_argument("schools", nargs="+")
            p.add_argument("--sync", action="store_true", help="run here instead of sending tasks")
    p = sub.add_parser("export")
    p.add_argument("--school", action="append")
    p.add_argument("--out", type=Path)
    p = sub.add_parser("status")
    p.add_argument("--budget", action="append", default=[BACKFILL_BUDGET])
    sub.add_parser("seed-files")
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        if args.command == "status":
            print(json.dumps(status(session, args.budget), ensure_ascii=False, default=str))
            return 0
        if args.command == "seed-files":
            print(json.dumps({"added": seed_from_files(session)}))
            return 0
        if args.command == "export":
            schools = args.school or sorted(set(session.scalars(
                select(CollectPage.school_key).where(CollectPage.result.is_not(None)))))
            for key in schools:
                print(json.dumps(export_school(session, key, out_dir=args.out), ensure_ascii=False))
            return 0

        from app import worker

        if args.command == "discover":
            for key in args.schools:
                if args.sync:
                    print(json.dumps(worker.run_discover(key, args.budget, args.cap), ensure_ascii=False))
                else:
                    worker.discover_task.delay(key, args.budget, args.cap)
            return 0
        states = ["pending", "queued"] if args.command == "resume" else args.state.split(",")
        query = select(CollectPage).where(CollectPage.state.in_(states))
        if getattr(args, "school", None):
            query = query.where(CollectPage.school_key.in_(args.school))
        ids = mark_queued(session, list(session.scalars(query.order_by(CollectPage.created_at))))
        for page_id in ids:
            worker.page_task.delay(page_id, args.budget, args.cap)
        print(json.dumps({"enqueued": len(ids)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
