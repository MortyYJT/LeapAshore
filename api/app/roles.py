"""Account roles (openspec knowledge-gaps D6): granted only from the server shell.

    python -m app.roles list
    python -m app.roles grant <email>
    python -m app.roles revoke <email>

`admin` is the only role: it may review knowledge gaps (`/api/admin/...`). No endpoint can grant it.
The account must exist, so the person logs in once (login mode) before being granted.
"""

import argparse
import json
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.account import Account
from app.services.auth import normalize_email

ADMIN = "admin"


def _set(session: Session, email: str, role: str | None) -> bool:
    account = session.scalar(select(Account).where(Account.email == normalize_email(email)))
    if account is None:
        return False
    account.role = role
    session.commit()
    return True


def grant(session: Session, email: str) -> bool:
    return _set(session, email, ADMIN)


def revoke(session: Session, email: str) -> bool:
    return _set(session, email, None)


def admins(session: Session) -> list[str]:
    return list(session.scalars(select(Account.email).where(Account.role == ADMIN).order_by(Account.email)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("list", "grant", "revoke"))
    parser.add_argument("email", nargs="?")
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        if args.command == "list":
            print(json.dumps({"admins": admins(session)}, ensure_ascii=False))
            return 0
        if not args.email:
            parser.error("an email is needed")
        done = (grant if args.command == "grant" else revoke)(session, args.email)
    if not done:
        print("no account with that email; it has to log in once first", file=sys.stderr)
        return 1
    print(json.dumps({args.command: normalize_email(args.email)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
