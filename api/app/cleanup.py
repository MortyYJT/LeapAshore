"""Sweep data nobody can use any more (openspec/changes/archive/2026-10-30-account-login, D10).

    python -m app.cleanup            # report only
    python -m app.cleanup --apply    # delete

- anonymous subjects (no account) not seen for `ANONYMOUS_RETENTION_DAYS` (90), with their files and
  advisor conversations;
- expired sessions;
- login codes older than two days (the daily rate limits only look back 24 hours);
- advisor conversations untouched for `ADVISOR_THREAD_RETENTION_DAYS` (90), whoever they belong to
  (openspec advisor-persistence D7);
- knowledge-gap reports (a refused question and its asker's hash) older than
  `KNOWLEDGE_GAP_RETENTION_DAYS` (90); the gaps stay (openspec knowledge-gaps D5).

    python -m app.cleanup --conversations-only [--apply]   # the last two items alone

In production the Celery beat runs it daily with `--apply` (`app.worker.cleanup`, openspec/changes/
archive/2026-10-30-collect-queue D12); in anonymous mode only the conversation and report sweeps run, since every subject
is anonymous there.
"""

import argparse
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models.account import Account, AuthSession, LoginCode
from app.models.client import Client
from app.services import knowledge_gaps
from app.services.accounts import delete_subject
from app.services.conversations import delete_threads, stale_threads

CODE_RETENTION = timedelta(days=2)


def stale_anonymous_subjects(session: Session, now: datetime) -> list[str]:
    cutoff = now - timedelta(days=settings.anonymous_retention_days)
    return list(
        session.scalars(
            select(Client.id)
            .where(Client.last_seen_at < cutoff, ~exists().where(Account.client_id == Client.id))
            .order_by(Client.last_seen_at)
        )
    )


def sweep_conversations(session: Session, apply: bool, now: datetime | None = None) -> dict:
    """Delete advisor conversations nobody has touched for the retention period (D7), and knowledge-gap
    reports past theirs (knowledge-gaps D5): the two sweeps that run in every mode."""
    threads = stale_threads(session, now or datetime.now(UTC))
    report = {"apply": apply, "stale_conversations": len(threads)}
    if apply:
        delete_threads(session, threads)
        session.commit()
    report.update(knowledge_gaps.sweep_reports(session, apply=apply, now=now))
    return report


def run(session: Session, apply: bool, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    subjects = stale_anonymous_subjects(session, now)
    sessions = session.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.expires_at <= now))
    codes = session.scalar(
        select(func.count()).select_from(LoginCode).where(LoginCode.created_at < now - CODE_RETENTION)
    )
    report = {
        "apply": apply,
        "anonymous_subjects": len(subjects),
        "expired_sessions": sessions,
        "old_codes": codes,
        "stale_conversations": len(stale_threads(session, now)),
    }
    if not apply:
        report.update(knowledge_gaps.sweep_reports(session, apply=False, now=now))
        return report
    files = 0
    for client_id in subjects:
        # Re-checked under a lock: a login may have claimed it, or a request touched it, since the list
        # was read.
        row = session.scalar(select(Client).where(Client.id == client_id).with_for_update())
        cutoff = now - timedelta(days=settings.anonymous_retention_days)
        if (
            row is None
            or row.last_seen_at >= cutoff
            or session.scalar(select(exists().where(Account.client_id == client_id)))
        ):
            session.rollback()
            continue
        files += delete_subject(session, client_id)["files_removed"]
    session.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    session.execute(delete(LoginCode).where(LoginCode.created_at < now - CODE_RETENTION))
    session.commit()
    report["files_removed"] = files
    swept = sweep_conversations(session, apply=True, now=now)
    report["stale_conversations"], report["old_gap_reports"] = swept["stale_conversations"], swept["old_gap_reports"]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="delete; without it only report")
    parser.add_argument(
        "--conversations-only", action="store_true", help="only the advisor-conversation sweep (anonymous mode)"
    )
    args = parser.parse_args()
    with SessionLocal() as session:
        sweep = sweep_conversations if args.conversations_only else run
        print(json.dumps(sweep(session, apply=args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()
