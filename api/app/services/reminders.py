"""Deadline reminders by email (`docs/product/PRD-multi-device.md`, 3.4).

Once a day the beat runs `plan`, which claims what is due for every account, and one `deliver` task
per email mails it.

Who is reminded
    Accounts only: the address is the sign-in email. Reminders are on by default at 14, 7, 3 and 1
    days before a deadline, and each account can change the lead times or turn them off.

What is due
    An application counts while the applicant is still working on it: status 考虑中 (`considering`)
    or 准备中 (`applying`). 已提交, 收到录取, 未录取 and 已放弃 get nothing, nor does an unknown or a
    past deadline. Days left are counted between Beijing dates; a deadline is a date with no zone.

Catch-up
    A lead time is due on the day the deadline is exactly that many days away. If that day was
    missed (the worker was down, the send failed, the daily cap held it back) it may still go out
    during the next `CATCH_UP_DAYS` days, and only while no shorter lead time has come due: the
    nearest lead time is the only one ever sent, and an older missed one is dropped. So an outage of
    any length produces at most one reminder per application, and the email states the days actually
    left on the day it is sent.

Once only
    A reminder is one row of `reminder_deliveries`, unique over account, application, deadline date
    and lead time, inserted and committed before anything is mailed. A second worker, a redelivered
    task or a rerun inserts nothing (`ON CONFLICT DO NOTHING`) and so has nothing to mail. A changed
    deadline is a different row, which is what re-arms the reminder. The email row is then taken for
    an attempt with one conditional `UPDATE`, so two workers holding the same email id send once.

One email a day
    Planning holds the account's settings row, so a day's reminders for one account are claimed
    together into one email, and the count of that day's emails is compared with the daily cap under
    the same lock. What the cap holds back stays unclaimed and falls under the catch-up rule.

Failure
    A send that certainly did not go out is retried with backoff, `MAX_ATTEMPTS` times in all, then
    recorded as `failed` and its claims released, so the catch-up rule may plan it again the next
    day. A send that may have gone out (the server went quiet after taking the message) is recorded
    as `uncertain` and never retried: at most once outranks at least once here. An email is only
    ever sent on its own day; one left over is expired and its reminders planned afresh, so the text
    is always written for the day it is read.

What is said
    The email is written at the moment of sending from the records as they then read; a claim whose
    record has since changed deadline, been closed or been removed is left out. See
    `app.services.reminder_copy` for the wording rule.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import Account
from app.models.reminder import ReminderDelivery, ReminderEmail, ReminderSettings
from app.services import application_records as records
from app.services import mail, reminder_copy
from app.services.versions import StaleVersion

log = logging.getLogger(__name__)

BEIJING = ZoneInfo("Asia/Shanghai")
DEFAULT_LEAD_DAYS = (14, 7, 3, 1)
MIN_LEAD, MAX_LEAD, MAX_LEADS = 1, 90, 6
# 考虑中 and 准备中: the applicant has not submitted, been answered or given up.
ACTIVE_STATUSES = frozenset({"considering", "applying"})
CATCH_UP_DAYS = 2
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = (60, 300, 1800)
# Statuses of an email that count against the day's cap: everything that went out or still may.
COUNTED = ("pending", "sending", "retry", "sent", "uncertain")
WAITING = ("pending", "retry")
# How long the records of what was sent are kept.
KEEP_CLAIMS_DAYS = 30
KEEP_EMAILS_DAYS = 180

_PURPOSE = b"leapashore.reminders.unsubscribe.v1:"


@dataclass(frozen=True)
class Due:
    record_key: str
    deadline: date
    lead_days: int


# --- arithmetic ----------------------------------------------------------------------------------


def beijing_date(instant: datetime) -> date:
    """The calendar date in Beijing at `instant`, which must carry a zone."""
    if instant.tzinfo is None:
        raise ValueError("an instant without a zone has no Beijing date")
    return instant.astimezone(BEIJING).date()


def days_left(deadline: date, today: date) -> int:
    return (deadline - today).days


def due_lead(left: int, leads: Iterable[int], catch_up: int = CATCH_UP_DAYS) -> int | None:
    """The lead time to send with `left` days to go, or None.

    The nearest lead time that has come due (the smallest one not below `left`), provided its own
    day is at most `catch_up` days back. A longer lead time that was missed is never returned.
    """
    if left < 0:
        return None
    reached = [lead for lead in leads if lead >= left]
    if not reached:
        return None
    nearest = min(reached)
    return nearest if nearest - left <= catch_up else None


def backoff_delay(attempts: int) -> int:
    """Seconds to wait before the next try, after `attempts` tries have failed."""
    return BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1]


# --- settings ------------------------------------------------------------------------------------


def settings_for(session: Session, account_id: str, *, lock: bool = False) -> ReminderSettings:
    """The account's settings row, created with the defaults on first use; locked when asked."""

    def read():
        query = select(ReminderSettings).where(ReminderSettings.account_id == account_id)
        if lock:
            query = query.with_for_update()
        return session.scalars(query.execution_options(populate_existing=True)).first()

    row = read()
    if row is None:
        # Two first uses at once: the loser's insert does nothing and it reads the winner's row.
        session.execute(
            pg_insert(ReminderSettings)
            .values(
                account_id=account_id,
                enabled=True,
                lead_days=list(DEFAULT_LEAD_DAYS),
                unsubscribe_key=secrets.token_hex(32),
                version=1,
            )
            .on_conflict_do_nothing(index_elements=["account_id"])
        )
        row = read()
    return row


def settings_view(row: ReminderSettings) -> dict:
    return {
        "enabled": row.enabled,
        "leadDays": list(row.lead_days),
        "unsubscribedAt": row.unsubscribed_at,
        "version": str(row.version),
    }


def read_settings(session: Session, account_id: str) -> dict:
    view = settings_view(settings_for(session, account_id))
    session.commit()
    return view


def update_settings(
    session: Session,
    account_id: str,
    base_version: str,
    *,
    enabled: bool | None = None,
    lead_days: list[int] | None = None,
) -> dict:
    """Apply a change based on the stored version; `StaleVersion` with the stored state otherwise.

    The row is locked from the comparison to the commit, as every versioned record's update is, so
    two devices saving together are handled one after the other and the second is refused.
    """
    row = settings_for(session, account_id, lock=True)
    if base_version != str(row.version):
        current = settings_view(row)
        session.commit()
        raise StaleVersion(current)
    if enabled is not None:
        row.enabled = enabled
        if enabled:
            row.unsubscribed_at = None
    if lead_days is not None:
        row.lead_days = sorted(lead_days, reverse=True)
    session.commit()
    session.refresh(row)
    return settings_view(row)


# --- the unsubscribe link ------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _signature(key_hex: str, account_id: str) -> str:
    digest = hmac.new(bytes.fromhex(key_hex), _PURPOSE + account_id.encode(), hashlib.sha256).digest()
    return _b64(digest)


def unsubscribe_token(row: ReminderSettings) -> str:
    """`<account id>.<HMAC-SHA256>`, both base64url.

    Signed with the account's own random key, over a purpose string and the account id. The only
    code that accepts it is `unsubscribe`, which can do one thing: turn that account's reminders
    off. It is not a session, names no email address, and is the same in every email, so a link in
    an old email keeps working.
    """
    return f"{_b64(uuid.UUID(row.account_id).bytes)}.{_signature(row.unsubscribe_key, row.account_id)}"


def unsubscribe(session: Session, token: str) -> bool:
    """Turn reminders off for the account the token was signed for. False for any other string.

    Using a link twice is not an error: the second use finds reminders off and changes nothing.
    """
    if not isinstance(token, str) or not 0 < len(token) <= 128:
        return False
    who, dot, signature = token.partition(".")
    if not dot or "." in signature:
        return False
    try:
        account_id = str(uuid.UUID(bytes=base64.urlsafe_b64decode(who.encode("ascii") + b"==")))
        given = signature.encode("ascii")
    except (ValueError, UnicodeEncodeError):
        return False
    if _b64(uuid.UUID(account_id).bytes) != who:
        return False
    row = session.scalars(
        select(ReminderSettings).where(ReminderSettings.account_id == account_id).with_for_update()
    ).first()
    # Compare against something either way, so a missing account answers in the same time.
    expected = _signature(row.unsubscribe_key if row else "00" * 32, account_id)
    if not hmac.compare_digest(expected.encode("ascii"), given) or row is None:
        session.rollback()
        return False
    if row.enabled:
        row.enabled = False
        row.unsubscribed_at = datetime.now(UTC)
        log.info("reminders turned off by an email link")
    session.commit()
    return True


def unsubscribe_links(row: ReminderSettings) -> tuple[str, str]:
    """The header's one-click URL and the page the body links, for this account."""
    base = settings.public_base_url.rstrip("/")
    token = quote(unsubscribe_token(row), safe="")
    return f"{base}/api/reminders/unsubscribe?token={token}", f"{base}/reminders/unsubscribe?token={token}"


# --- what is due ---------------------------------------------------------------------------------


def _active(record: dict, today: date) -> bool:
    return (
        record["status"] in ACTIVE_STATUSES
        and record["deadline"] is not None
        and record["deadline"] >= today
    )


def due_items(session: Session, client_id: str, leads: Iterable[int], today: date) -> list[Due]:
    """Every reminder of this subject that is due today, claimed or not, nearest deadline first."""
    leads = list(leads)
    due = []
    for record in records.read_records(client_id, session):
        if not _active(record, today):
            continue
        lead = due_lead(days_left(record["deadline"], today), leads)
        if lead is not None:
            due.append(Due(record["id"], record["deadline"], lead))
    return sorted(due, key=lambda item: (item.deadline, item.record_key))


def _unclaimed(session: Session, account_id: str, due: list[Due]) -> list[Due]:
    if not due:
        return []
    taken = {
        tuple(row)
        for row in session.execute(
            select(ReminderDelivery.record_key, ReminderDelivery.deadline, ReminderDelivery.lead_days).where(
                ReminderDelivery.account_id == account_id,
                ReminderDelivery.record_key.in_({item.record_key for item in due}),
            )
        )
    }
    return [item for item in due if (item.record_key, item.deadline, item.lead_days) not in taken]


def _emails_on(session: Session, account_id: str, day: date) -> int:
    return session.scalar(
        select(func.count())
        .select_from(ReminderEmail)
        .where(
            ReminderEmail.account_id == account_id,
            ReminderEmail.send_date == day,
            ReminderEmail.status.in_(COUNTED),
        )
    )


def claim(session: Session, account_id: str, email_id: str, items: list[Due]) -> list[Due]:
    """Insert the claims and return the ones this transaction won. The caller commits.

    The unique constraint decides: a row another transaction has inserted, committed or not, is
    waited for and then skipped, so of any number of writers exactly one gets each reminder.
    """
    if not items:
        return []
    rows = session.execute(
        pg_insert(ReminderDelivery)
        .values(
            [
                {
                    "id": str(uuid.uuid4()),
                    "account_id": account_id,
                    "record_key": item.record_key,
                    "deadline": item.deadline,
                    "lead_days": item.lead_days,
                    "email_id": email_id,
                }
                for item in items
            ]
        )
        .on_conflict_do_nothing(constraint="uq_reminder_deliveries_once")
        .returning(ReminderDelivery.record_key, ReminderDelivery.deadline, ReminderDelivery.lead_days)
    ).all()
    return sorted((Due(*row) for row in rows), key=lambda item: (item.deadline, item.record_key))


def _item_json(item: Due) -> dict:
    return {"recordKey": item.record_key, "deadline": item.deadline.isoformat(), "leadDays": item.lead_days}


def plan_account(session: Session, account: Account, today: date) -> str | None:
    """Claim what is due today for one account into one email. Returns its id, or None. Commits."""
    account_id, client_id = account.id, account.client_id
    row = settings_for(session, account_id, lock=True)
    fresh: list[Due] = []
    if row.enabled:
        fresh = _unclaimed(session, account_id, due_items(session, client_id, row.lead_days, today))
    if not fresh or _emails_on(session, account_id, today) >= settings.reminder_daily_cap:
        session.commit()
        return None
    email = ReminderEmail(id=str(uuid.uuid4()), account_id=account_id, send_date=today, status="pending", items=[])
    session.add(email)
    session.flush()
    won = claim(session, account_id, email.id, fresh)
    if not won:
        session.rollback()
        return None
    email.items = [_item_json(item) for item in won]
    email_id = email.id
    session.commit()
    return email_id


def _sweep(session: Session, today: date, account_ids: list[str] | None) -> None:
    """Close what earlier days left open, and drop records past their keep time."""

    def scoped(statement, column):
        return statement if account_ids is None else statement.where(column.in_(account_ids))

    # Never attempted, or waiting for a retry, on a day that is over: not sent, so released.
    expired = list(
        session.scalars(
            scoped(
                update(ReminderEmail)
                .where(ReminderEmail.send_date < today, ReminderEmail.status.in_(WAITING))
                .values(status="expired")
                .returning(ReminderEmail.id),
                ReminderEmail.account_id,
            )
        )
    )
    if expired:
        session.execute(delete(ReminderDelivery).where(ReminderDelivery.email_id.in_(expired)))
    # Taken for an attempt and never closed: the worker died mid-send, and it may have gone out.
    session.execute(
        scoped(
            update(ReminderEmail)
            .where(ReminderEmail.send_date < today, ReminderEmail.status == "sending")
            .values(status="uncertain", last_error="WorkerLost"),
            ReminderEmail.account_id,
        )
    )
    session.execute(
        scoped(
            delete(ReminderDelivery).where(ReminderDelivery.deadline < today - timedelta(days=KEEP_CLAIMS_DAYS)),
            ReminderDelivery.account_id,
        )
    )
    session.execute(
        scoped(
            delete(ReminderEmail).where(ReminderEmail.send_date < today - timedelta(days=KEEP_EMAILS_DAYS)),
            ReminderEmail.account_id,
        )
    )
    session.commit()


def _refusal() -> str | None:
    """Why the job may not run at all, if it may not."""
    if not settings.auth_enabled:
        return "AUTH_ENABLED is off: reminders go to sign-in addresses, and there are none"
    if settings.is_production and not settings.public_base_url.startswith("https://"):
        return "PUBLIC_BASE_URL is not an https origin: the links in the email would not work"
    return None


def _account_ids(session: Session, accounts: Iterable[Account] | None) -> tuple[list[str], list[str] | None]:
    if accounts is None:
        return list(session.scalars(select(Account.id).order_by(Account.created_at, Account.id))), None
    ids = [account.id for account in accounts]
    return ids, ids


def plan(session: Session, now: datetime, accounts: Iterable[Account] | None = None) -> dict:
    """Claim today's reminders for every account (or the ones given) and say which emails to deliver.

    `emails` are the ones this run created; `waiting` are today's emails an earlier run created that
    have not been sent yet, handed back so a rerun also restarts a delivery the broker lost. One
    account's failure is counted and skipped; the rest are still planned.
    """
    today = beijing_date(now)
    report: dict = {"date": today.isoformat(), "accounts": 0, "emails": [], "waiting": [], "errors": 0}
    refusal = _refusal()
    if refusal:
        return {**report, "skipped": refusal}
    ids, scope = _account_ids(session, accounts)
    report["accounts"] = len(ids)
    if not ids:
        return report
    _sweep(session, today, scope)
    waiting_query = select(ReminderEmail.id).where(
        ReminderEmail.send_date == today, ReminderEmail.status.in_(WAITING), ReminderEmail.account_id.in_(ids)
    )
    report["waiting"] = list(session.scalars(waiting_query.order_by(ReminderEmail.created_at)))
    for account_id in ids:
        try:
            account = session.get(Account, account_id)
            email_id = plan_account(session, account, today) if account is not None else None
        except Exception as error:  # noqa: BLE001 - one account's failure must not stop the others
            session.rollback()
            report["errors"] += 1
            log.error("reminder planning failed for account %s: %s", account_id, type(error).__name__)
            continue
        if email_id:
            report["emails"].append(email_id)
    log.info(
        "reminders planned for %s: %d accounts, %d emails, %d waiting, %d errors",
        today.isoformat(), len(ids), len(report["emails"]), len(report["waiting"]), report["errors"],
    )
    return report


def preview(session: Session, now: datetime, accounts: Iterable[Account] | None = None) -> dict:
    """What `plan` would claim now, without writing or mailing: counts and application ids only."""
    today = beijing_date(now)
    report: dict = {"date": today.isoformat(), "accounts": 0, "enabled": 0, "emails": 0, "reminders": 0,
                    "heldByCap": 0, "items": []}
    refusal = _refusal()
    if refusal:
        report["skipped"] = refusal
    try:
        pairs = [
            (account.id, account.client_id)
            for account in (accounts if accounts is not None else session.scalars(select(Account)))
        ]
        report["accounts"] = len(pairs)
        for number, (account_id, client_id) in enumerate(pairs, 1):
            row = session.get(ReminderSettings, account_id)
            if row is not None and not row.enabled:
                continue
            report["enabled"] += 1
            leads = row.lead_days if row is not None else DEFAULT_LEAD_DAYS
            fresh = _unclaimed(session, account_id, due_items(session, client_id, leads, today))
            if not fresh:
                continue
            if _emails_on(session, account_id, today) >= settings.reminder_daily_cap:
                report["heldByCap"] += len(fresh)
                continue
            report["emails"] += 1
            report["reminders"] += len(fresh)
            report["items"] += [
                {"email": number, "application": item.record_key, "leadDays": item.lead_days,
                 "daysLeft": days_left(item.deadline, today)}
                for item in fresh
            ]
    finally:
        session.rollback()
    return report


# --- delivery ------------------------------------------------------------------------------------


def _close(session: Session, email_id: str, status: str, error: Exception | None = None, *, release: bool = False,
           sent_at: datetime | None = None) -> str:
    values: dict = {"status": status}
    if error is not None:
        cause = error.__cause__
        values["last_error"] = type(error).__name__ + (f"({type(cause).__name__})" if cause is not None else "")
    if sent_at is not None:
        values["sent_at"] = sent_at
    session.execute(update(ReminderEmail).where(ReminderEmail.id == email_id).values(**values))
    if release:
        session.execute(delete(ReminderDelivery).where(ReminderDelivery.email_id == email_id))
    session.commit()
    log.info("reminder email %s: %s (%s)", email_id, status, values.get("last_error", "no error"))
    return status


def _entries(session: Session, client_id: str, email_id: str, today: date) -> list[reminder_copy.Entry]:
    """The claimed reminders whose record still reads as it was claimed, nearest deadline first."""
    claimed = {
        (key, deadline)
        for key, deadline in session.execute(
            select(ReminderDelivery.record_key, ReminderDelivery.deadline).where(ReminderDelivery.email_id == email_id)
        )
    }
    entries = [
        reminder_copy.Entry(
            school=record["school"],
            name=record["name"],
            round=record["round"] or None,
            deadline=record["deadline"],
            days_left=days_left(record["deadline"], today),
            source_url=record["sourceUrl"] or None,
            checked_at=record["checkedAt"],
            origin=record["deadlineOrigin"],
        )
        for record in records.read_records(client_id, session)
        if _active(record, today) and (record["id"], record["deadline"]) in claimed
    ]
    return sorted(entries, key=lambda entry: (entry.deadline, entry.school, entry.name))


def deliver(session: Session, email_id: str, now: datetime) -> str:
    """Send one claimed email, once. Returns the status it was left in, or `not pending`.

    `retry` asks the caller to call again after `backoff_delay(attempts)`; every other answer is
    final. Safe to call any number of times and from any number of workers: only the call that moves
    the row from waiting to `sending` goes on to mail.
    """
    today = beijing_date(now)
    stale = session.execute(
        update(ReminderEmail)
        .where(ReminderEmail.id == email_id, ReminderEmail.status.in_(WAITING), ReminderEmail.send_date != today)
        .values(status="expired")
        .returning(ReminderEmail.id)
    ).first()
    if stale is not None:
        return _close(session, email_id, "expired", release=True)
    taken = session.execute(
        update(ReminderEmail)
        .where(ReminderEmail.id == email_id, ReminderEmail.status.in_(WAITING))
        .values(status="sending", attempts=ReminderEmail.attempts + 1, attempted_at=now)
        .returning(ReminderEmail.account_id, ReminderEmail.attempts)
    ).first()
    session.commit()
    if taken is None:
        return "not pending"
    account_id, attempts = taken

    account = session.get(Account, account_id)
    row = settings_for(session, account_id)
    if account is None or row is None or not row.enabled:
        return _close(session, email_id, "cancelled")
    entries = _entries(session, account.client_id, email_id, today)
    if not entries:
        return _close(session, email_id, "cancelled")
    one_click, page = unsubscribe_links(row)
    applications_url = f"{settings.public_base_url.rstrip('/')}/applications"
    subject = reminder_copy.subject(entries)
    message = mail.ReminderMessage(
        to=account.email,
        subject=subject,
        text=reminder_copy.text(entries, applications_url, page),
        html=reminder_copy.html(entries, applications_url, page, subject),
        unsubscribe_url=one_click,
        unsubscribe_page=page,
        reference=email_id,
    )
    # Nothing is held in the database while the mail server is spoken to.
    session.commit()
    try:
        mail.send_reminder(message)
    except mail.MailUncertain as error:
        return _close(session, email_id, "uncertain", error)
    except mail.MailError as error:
        if attempts >= MAX_ATTEMPTS:
            return _close(session, email_id, "failed", error, release=True)
        return _close(session, email_id, "retry", error)
    except Exception as error:  # noqa: BLE001 - an unknown failure may have followed the hand-over
        return _close(session, email_id, "uncertain", error)
    return _close(session, email_id, "sent", sent_at=datetime.now(UTC))


def attempts_of(session: Session, email_id: str) -> int:
    return session.scalar(select(ReminderEmail.attempts).where(ReminderEmail.id == email_id)) or 0
