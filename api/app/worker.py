"""Celery: the collection queue's tasks and the beat schedule (openspec/changes/collect-queue).

    celery -A app.worker worker --pool threads --concurrency 4 --loglevel INFO
    celery -A app.worker beat --loglevel INFO

The queue's state is in `collect_pages` (D1); the broker only carries page ids, so losing it loses
nothing that `python -m app.collect.queue resume` cannot re-send. Tasks are acknowledged after they
finish (`acks_late`) and re-delivered when their worker dies.
"""

import logging
from datetime import UTC, datetime

import redis
from celery import Celery
from sqlalchemy import select
from celery.schedules import crontab

from app.collect import queue
from app.collect.ratelimit import HostBucket, RetryLater
from app.collect.snapshot import MIN_INTERVAL, SNAPSHOT_ROOT, use_limiter
from app.config import settings
from app.db import SessionLocal
from app.models.collect import CollectPage, PageState

log = logging.getLogger(__name__)

app = Celery("leapashore", broker=settings.celery_broker_url)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    timezone="Asia/Shanghai",
    enable_utc=True,
    broker_transport_options={"visibility_timeout": 2 * 3600},
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "recollect-due-pages": {"task": "collect.recollect_due", "schedule": crontab(hour=4, minute=7)},
        "cleanup-anonymous-data": {"task": "maintenance.cleanup", "schedule": crontab(hour=3, minute=17)},
        # New or renamed programs get their vectors within the hour (openspec hybrid-retrieval D5).
        "embed-programs": {"task": "maintenance.embed_programs", "schedule": crontab(minute=37)},
    },
)


def _redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, socket_timeout=10, socket_connect_timeout=10)


def _budget(client: redis.Redis, key: str, cap: float) -> queue.Budget:
    if key.startswith("daily:"):
        return queue.daily_budget(client)
    return queue.Budget(client, key, cap)


def _limiter(client: redis.Redis) -> HostBucket:
    return HostBucket(client, settings.limits_key_prefix, MIN_INTERVAL)


@app.task(name="collect.page", bind=True)
def page_task(self, page_id: str, budget_key: str, budget_cap: float) -> str:
    client = _redis()
    lock = client.set(f"{settings.limits_key_prefix}collect:lock:{page_id}", "1", nx=True, ex=900)
    if not lock:
        return "running elsewhere"
    try:
        with SessionLocal() as session:
            page = session.get(CollectPage, page_id)
            if page is None or page.state != PageState.QUEUED:
                return "not queued"
            try:
                with use_limiter(_limiter(client)):
                    return queue.collect_page(session, page_id, budget=_budget(client, budget_key, budget_cap),
                                              outage=queue.ModelOutage(client))
            except RetryLater as later:
                # The host's turn is far away: back on the queue, not counted as a retry (D3).
                page_task.apply_async((page_id, budget_key, budget_cap), countdown=later.delay)
                return "rescheduled"
            except queue.Transient as error:
                session.rollback()
                page = session.get(CollectPage, page_id)
                if self.request.retries >= queue.MAX_RETRIES:
                    page.state, page.last_error = PageState.FAILED, f"after {queue.MAX_RETRIES} retries: {error}"
                    session.commit()
                    return PageState.FAILED
                raise self.retry(exc=error, countdown=queue.backoff_delay(self.request.retries),
                                 max_retries=queue.MAX_RETRIES) from error
            except Exception as error:  # noqa: BLE001 - an unexpected error must not leave the row queued forever
                log.exception("page %s failed", page_id)
                session.rollback()
                page = session.get(CollectPage, page_id)
                page.state, page.last_error = PageState.FAILED, f"{type(error).__name__}: {str(error)[:300]}"
                session.commit()
                return PageState.FAILED
    finally:
        client.delete(f"{settings.limits_key_prefix}collect:lock:{page_id}")


def run_discover(school_key: str, budget_key: str, budget_cap: float) -> dict:
    """Discovery for one school, then a page task for each new page (D11)."""
    from app.collect.discover import discover_school

    client = _redis()
    with SessionLocal() as session, use_limiter(_limiter(client)):
        report = discover_school(session, school_key, budget=_budget(client, budget_key, budget_cap))
        ids = queue.mark_queued(session, list(session.scalars(
            select(CollectPage).where(CollectPage.school_key == school_key,
                                            CollectPage.state == PageState.PENDING))))
    for page_id in ids:
        page_task.delay(page_id, budget_key, budget_cap)
    report["enqueued"] = len(ids)
    return report


@app.task(name="collect.discover", bind=True, max_retries=3)
def discover_task(self, school_key: str, budget_key: str, budget_cap: float) -> dict:
    try:
        return run_discover(school_key, budget_key, budget_cap)
    except RetryLater as later:
        raise self.retry(countdown=later.delay, max_retries=None) from later


@app.task(name="collect.recollect_due")
def recollect_due() -> dict:
    """Seed rows for committed programs, then send the pages not fetched for 30 days (D12)."""
    with SessionLocal() as session:
        seeded = queue.seed_from_files(session)
        pages = queue.due_pages(session, datetime.now(UTC), settings.collect_recollect_per_day)
        ids = queue.mark_queued(session, pages)
    key = f"daily:{datetime.now(queue.BEIJING).date().isoformat()}"
    for page_id in ids:
        page_task.delay(page_id, key, settings.collect_daily_budget_cny)
    return {"seeded": seeded, "enqueued": len(ids)}


@app.task(name="maintenance.cleanup")
def cleanup() -> dict:
    """The 90-day sweeps (D12; handoff "切到登录模式" step 6).

    Anonymous subjects are swept only in login mode: with it off every user is anonymous. Advisor
    conversations untouched for 90 days and knowledge-gap reports older than 90 days are swept in both
    modes (openspec advisor-persistence D7, knowledge-gaps D5).
    """
    from app import cleanup as sweep

    with SessionLocal() as session:
        if not settings.auth_enabled:
            return {
                "skipped": "AUTH_ENABLED is off: every user is anonymous, the subject sweep is for login mode",
                **sweep.sweep_conversations(session, apply=True),
            }
        return sweep.run(session, apply=True)


@app.task(name="maintenance.embed_programs")
def embed_programs() -> dict:
    """Embed programs, then page chunks, whose vector is missing or stale, at most
    `EMBED_BACKFILL_PER_RUN` of each a run. Without
    a key it does nothing; a service error ends the run, and the next run resumes."""
    from app.agent import embeddings

    client = embeddings.configured_client()
    if client is None:
        return {"skipped": "EMBED_API_KEY is not set"}
    report = embeddings.backfill(SessionLocal, client, batch_size=settings.embed_batch_size,
                                 limit=settings.embed_backfill_per_run)
    if "error" in report:
        log.warning("embedding backfill stopped: %s", report["error"])
        return report
    # Then the official page chunks (openspec snapshot-rag D10); the first fill is the CLI's.
    chunk_report = embeddings.backfill(SessionLocal, client, batch_size=settings.embed_batch_size,
                                       limit=settings.embed_backfill_per_run, chunks=True)
    if "error" in chunk_report:
        log.warning("chunk embedding backfill stopped: %s", chunk_report["error"])
    return {**report, "chunks": chunk_report}


__all__ = ["app", "page_task", "discover_task", "recollect_due", "cleanup", "embed_programs", "SNAPSHOT_ROOT"]
