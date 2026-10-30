"""The advisor's stored conversations, seen from the data subject (openspec advisor-persistence D7).

A conversation is a LangGraph thread whose id is ``{subject}:{conversation_id}``; its rows are spread
over ``checkpoints``, ``checkpoint_blobs`` and ``checkpoint_writes``. These functions run plain SQL in
the caller's SQLAlchemy session, so deleting or merging a subject removes or moves its conversations in
the same transaction as its other rows. None of them commit.
"""

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

THREAD_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")

# Every thread id that starts with the prefix, in any of the three tables: a run saves a step's writes
# in the background, so a thread can have writes or blobs whose checkpoint is not saved yet.
_THREADS_WITH_PREFIX = text(
    " UNION ".join(f"SELECT thread_id FROM {t} WHERE starts_with(thread_id, :prefix)" for t in THREAD_TABLES)
)


def _prefix(subject: str) -> str:
    return f"{subject}:"


def threads_of(session: Session, subject: str) -> list[str]:
    return sorted(session.scalars(_THREADS_WITH_PREFIX, {"prefix": _prefix(subject)}))


def delete_threads(session: Session, thread_ids: list[str]) -> int:
    if not thread_ids:
        return 0
    for table in THREAD_TABLES:
        session.execute(text(f"DELETE FROM {table} WHERE thread_id = ANY(:ids)"), {"ids": thread_ids})
    return len(thread_ids)


def delete_conversations(session: Session, subject: str) -> int:
    """Delete every conversation of a subject; returns how many threads there were."""
    return delete_threads(session, threads_of(session, subject))


def move_conversations(session: Session, source: str, target: str) -> dict[str, int]:
    """Give the anonymous subject's conversations to the account it merges into (account-login D7).

    The target's rows win, as for everything else in a merge: a conversation id the target already
    has is dropped from the source rather than mixed into the target's thread. A paused change moves
    with its thread, so a visitor who logs in to answer a confirm finds it still waiting; the tools read
    the subject from the run, so the change is written to the account.
    """
    if source == target:
        return {"moved": 0, "dropped": 0}
    taken = set(threads_of(session, target))
    moved: list[str] = []
    dropped: list[str] = []
    for old in threads_of(session, source):
        new = _prefix(target) + old[len(_prefix(source)) :]
        (dropped if new in taken else moved).append(old)
    delete_threads(session, dropped)
    for old in moved:
        new = _prefix(target) + old[len(_prefix(source)) :]
        for table in THREAD_TABLES:
            session.execute(text(f"UPDATE {table} SET thread_id = :new WHERE thread_id = :old"), {"new": new, "old": old})
        # LangChain copies the run's `client_id` into each checkpoint's metadata; keep it truthful.
        session.execute(
            text(
                "UPDATE checkpoints SET metadata = jsonb_set(metadata, '{client_id}', to_jsonb(CAST(:target AS text)))"
                " WHERE thread_id = :new AND metadata ? 'client_id'"
            ),
            {"target": target, "new": new},
        )
    return {"moved": len(moved), "dropped": len(dropped)}


def stale_threads(session: Session, now: datetime) -> list[str]:
    """Threads whose newest checkpoint is older than the retention period (D7).

    The time is the checkpoint's own ``ts`` (ISO 8601 with offset, written by LangGraph); the tables
    have no timestamp column of their own.
    """
    cutoff = now - timedelta(days=settings.advisor_thread_retention_days)
    return list(
        session.scalars(
            text(
                "SELECT thread_id FROM checkpoints GROUP BY thread_id"
                " HAVING max(CAST(checkpoint ->> 'ts' AS timestamptz)) < :cutoff ORDER BY thread_id"
            ),
            {"cutoff": cutoff},
        )
    )
