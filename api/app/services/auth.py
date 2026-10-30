"""Email-code login and server-side sessions (openspec/changes/archive/2026-10-30-account-login, D3-D7).

Rate limits live in PostgreSQL for now: the volume is small and Redis arrives with the advisor
limits in the next item. Every rule that has to hold under concurrency is enforced by a lock:

- sending: `pg_advisory_xact_lock` on the email, so two sends cannot both pass the 60-second check;
- verifying: the code row is read `FOR UPDATE`, so concurrent guesses are counted one at a time;
- first login: `INSERT ... ON CONFLICT (email) DO NOTHING`, so two first logins create one account;
- merging: the anonymous client row is locked, so it is claimed or merged once.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import Account, AuthSession, LoginCode
from app.models.client import new_client_id
from app.services import mail
from app.services.accounts import is_claimable, lock_client, merge_subject, new_subject

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 254


class AuthError(Exception):
    """A refusal with an HTTP status and a machine-readable code the interface switches on."""

    def __init__(self, status: int, code: str, message: str, **extra) -> None:
        super().__init__(message)
        self.status = status
        self.detail = {"code": code, "message": message, **extra}


@dataclass
class LoginResult:
    account: Account
    created: bool
    token: str
    merged: dict = field(default_factory=dict)


def now() -> datetime:
    return datetime.now(UTC)


def normalize_email(raw: str) -> str | None:
    """Trimmed and lower-cased, or None when it is not a plausible address."""
    email = (raw or "").strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or not _EMAIL.match(email):
        return None
    return email


def _hash_code(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _retry_after(oldest: datetime, window: timedelta, at: datetime) -> int:
    return max(1, int((oldest + window - at).total_seconds()) + 1)


def request_code(session: Session, email: str, ip: str | None) -> None:
    """Store a new code for `email` and mail it, or raise `AuthError` (429 / 502)."""
    at = now()
    day = timedelta(days=1)
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"login-code:{email}"})

    recent = list(
        session.scalars(
            select(LoginCode.created_at)
            .where(LoginCode.email == email, LoginCode.created_at > at - day)
            .order_by(LoginCode.created_at)
        )
    )
    resend = timedelta(seconds=settings.auth_code_resend_seconds)
    if recent and recent[-1] > at - resend:
        wait = _retry_after(recent[-1], resend, at)
        raise AuthError(429, "too_soon", f"验证码已发送，请 {wait} 秒后再试。", retryAfter=wait)
    if len(recent) >= settings.auth_codes_per_email_per_day:
        wait = _retry_after(recent[0], day, at)
        raise AuthError(429, "daily_limit", "这个邮箱今天收验证码的次数已用完，请明天再试。", retryAfter=wait)
    if ip:
        from_ip = list(
            session.scalars(
                select(LoginCode.created_at)
                .where(LoginCode.ip == ip, LoginCode.created_at > at - day)
                .order_by(LoginCode.created_at)
            )
        )
        if len(from_ip) >= settings.auth_codes_per_ip_per_day:
            wait = _retry_after(from_ip[0], day, at)
            raise AuthError(429, "ip_limit", "这个网络今天发送验证码的次数已用完，请明天再试。", retryAfter=wait)

    # Only one code per email can be live, so guesses never spread across several codes.
    session.execute(
        update(LoginCode)
        .where(LoginCode.email == email, LoginCode.consumed_at.is_(None), LoginCode.invalidated_at.is_(None))
        .values(invalidated_at=at)
    )
    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(16)
    session.add(
        LoginCode(
            id=str(uuid.uuid4()),
            email=email,
            code_hash=_hash_code(salt, code),
            salt=salt,
            ip=ip,
            created_at=at,
            expires_at=at + timedelta(seconds=settings.auth_code_ttl_seconds),
            attempts=0,
        )
    )
    # Committed before sending: a failed send still counts toward the limits, so a broken mail
    # server cannot be used to hammer it.
    session.commit()
    try:
        mail.send_login_code(email, code)
    except mail.MailError as exc:
        raise AuthError(502, "send_failed", "验证码邮件发送失败，请稍后再试。") from exc


def _check_code(session: Session, email: str, code: str) -> None:
    """Consume the live code, or raise. Wrong guesses are committed before the refusal."""
    at = now()
    row = session.scalar(
        select(LoginCode)
        .where(LoginCode.email == email, LoginCode.consumed_at.is_(None), LoginCode.invalidated_at.is_(None))
        .order_by(LoginCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    expired = AuthError(400, "code_expired", "验证码已失效，请重新获取。")
    if row is None or row.expires_at <= at or row.attempts >= settings.auth_code_max_attempts:
        session.rollback()
        raise expired
    if not hmac.compare_digest(row.code_hash, _hash_code(row.salt, code.strip())):
        row.attempts += 1
        remaining = settings.auth_code_max_attempts - row.attempts
        if remaining <= 0:
            row.invalidated_at = at
        session.commit()
        if remaining <= 0:
            raise AuthError(400, "too_many_attempts", "错误次数太多，这个验证码已作废，请重新获取。")
        raise AuthError(400, "wrong_code", f"验证码不对，还可以再试 {remaining} 次。", remaining=remaining)
    row.consumed_at = at
    session.flush()


def _find_account(session: Session, email: str) -> Account | None:
    return session.scalar(select(Account).where(Account.email == email))


def login_account(session: Session, email: str, anonymous_client_id: str | None) -> tuple[Account, bool, dict]:
    """Return the account for `email`, creating it on first login, with the browser's data merged.

    A new account claims the browser's anonymous subject outright (no rows move); an existing account
    absorbs it by the rules in `merge_subject`. The caller commits.
    """
    lock_client(session, anonymous_client_id)
    claimable = is_claimable(session, anonymous_client_id)

    account = _find_account(session, email)
    created = False
    if account is None:
        with session.begin_nested() as savepoint:
            client_id = anonymous_client_id if claimable else new_client_id()
            if not claimable:
                new_subject(session, client_id)
            inserted = session.execute(
                insert(Account)
                .values(id=str(uuid.uuid4()), email=email, client_id=client_id)
                .on_conflict_do_nothing(index_elements=[Account.email])
                .returning(Account.id)
            ).scalar()
            if inserted is None:
                # Another login created the account between the lookup and the insert.
                savepoint.rollback()
            else:
                created = True
                claimable = False  # claimed, nothing left to merge
        account = _find_account(session, email)
    merged = {}
    if claimable and anonymous_client_id != account.client_id:
        merged = merge_subject(session, anonymous_client_id, account.client_id)
    account.last_login_at = now()
    return account, created, merged


def verify_code(
    session: Session,
    email: str,
    code: str,
    anonymous_client_id: str | None,
    ip: str | None,
    user_agent: str | None,
) -> LoginResult:
    _check_code(session, email, code)
    account, created, merged = login_account(session, email, anonymous_client_id)
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=hash_token(token),
            account_id=account.id,
            expires_at=now() + timedelta(days=settings.auth_session_days),
            ip=ip,
            user_agent=(user_agent or "")[:256] or None,
        )
    )
    session.commit()
    return LoginResult(account=account, created=created, token=token, merged=merged)


def account_for_token(session: Session, token: str | None) -> Account | None:
    if not token:
        return None
    return session.scalar(
        select(Account)
        .join(AuthSession, AuthSession.account_id == Account.id)
        .where(AuthSession.token_hash == hash_token(token), AuthSession.expires_at > func.now())
    )


def end_session(session: Session, token: str | None) -> None:
    if token:
        row = session.get(AuthSession, hash_token(token))
        if row is not None:
            session.delete(row)
            session.commit()
