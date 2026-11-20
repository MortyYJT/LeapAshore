"""Preview today's deadline reminders without sending anything.

    python -m app.reminders_cli --dry-run

Prints what the scheduled job would claim if it ran now: counts, and for each reminder the
application's id, its lead time and the days left. No address is read into the output, nothing is
written to the database and nothing is mailed. Sending is the beat's job (`reminders.send_due`, daily
at 09:07 Beijing time); this command has no way to send.
"""

import argparse
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models.account import Account
from app.services import reminders


def _accounts(session):
    return list(session.scalars(select(Account).order_by(Account.created_at, Account.id)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.reminders_cli", description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", required=True,
                        help="required: this command only previews")
    parser.parse_args(argv)
    with SessionLocal() as session:
        report = reminders.preview(session, datetime.now(UTC), accounts=_accounts(session))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
