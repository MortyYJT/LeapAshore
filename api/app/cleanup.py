"""Sweep data nobody can use any more (openspec/changes/account-login, D10).

    python -m app.cleanup            # report only
    python -m app.cleanup --apply    # delete

- anonymous subjects (no account) not seen for `ANONYMOUS_RETENTION_DAYS` (90), with their files;
- expired sessions;
- login codes older than two days (the daily rate limits only look back 24 hours).

In production the Celery beat runs it daily with `--apply` once login mode is on (`app.worker.cleanup`,
openspec/changes/collect-queue D12); in anonymous mode it does nothing.
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
from app.services.accounts import delete_subject

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


def run(session: Session, apply: bool, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    subjects = stale_anonymous_subjects(session, now)
    sessions = session.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.expires_at <= now))
    codes = session.scalar(
        select(func.count()).select_from(LoginCode).where(LoginCode.created_at < now - CODE_RETENTION)
    )
    report = {"apply": apply, "anonymous_subjects": len(subjects), "expired_sessions": sessions, "old_codes": codes}
    if not apply:
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
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="delete; without it only report")
    args = parser.parse_args()
    with SessionLocal() as session:
        print(json.dumps(run(session, apply=args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()
