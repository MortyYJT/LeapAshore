"""Deadline reminders by email (`docs/product/PRD-multi-device.md`, 3.4).

The rules under test:

- lead times are counted between Beijing dates;
- a reminder is claimed in the database before it is mailed, once per account, application, deadline
  date and lead time, so concurrent workers, a retried task and a rerun cannot mail it twice;
- a changed deadline is a new reminder; a missed day is caught up within bounds, never as a burst;
- one applicant gets one email a day (a digest) under a daily cap;
- a failed send is retried, recorded, and does not hold up anyone else;
- the email says only what the applicant's record says.

They run against the real PostgreSQL, like the rest of the suite. Every account is created by the
test, and the planner is always pointed at those accounts only, so a developer's own rows are never
claimed or mailed.
"""

import logging
import re
import smtplib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from email import message_from_bytes, policy

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models.account import Account
from app.models.application_plan import ApplicationPlan
from app.models.client import Client
from app.models.reminder import ReminderDelivery, ReminderEmail, ReminderSettings
from app.services import mail, reminders
from tests.auth_helpers import login, login_mode, new_client, outbox, unique_email  # noqa: F401

ROUNDS = 8
WORKERS = 6
# 09:07 in Beijing on 2026-11-20, the hour the beat runs the job.
NOW = datetime(2026, 11, 20, 1, 7, tzinfo=UTC)
TODAY = date(2026, 11, 20)


def at_once(*calls):
    barrier = threading.Barrier(len(calls))

    def run(call):
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [future.result(timeout=30) for future in futures]


def second_device(first):
    """Another client of the same account: its own connection, the same session cookie."""
    other = new_client()
    other.cookies.set("leapashore_session", first.cookies["leapashore_session"])
    return other


def make_account(session) -> Account:
    client = Client(id=str(uuid.uuid4()))
    session.add(client)
    session.flush()
    account = Account(id=str(uuid.uuid4()), email=unique_email(), client_id=client.id)
    session.add(account)
    session.commit()
    return account


def add_record(session, account, days: int | None, *, today=TODAY, **fields) -> ApplicationPlan:
    """A manual application whose deadline is `days` after `today` (None: unknown)."""
    plan = ApplicationPlan(
        id=str(uuid.uuid4()),
        client_id=account.client_id,
        school=fields.pop("school", "Example University"),
        name=fields.pop("name", f"MSc {uuid.uuid4().hex[:6]}"),
        status=fields.pop("status", "applying"),
        deadline=None if days is None else today + timedelta(days=days),
        deadline_override=days is not None,
        materials_ready=False,
        material_notes="",
        **fields,
    )
    session.add(plan)
    session.commit()
    return plan


class Sent:
    """Stands in for `mail.send_reminder`: records every message, or fails as told."""

    def __init__(self) -> None:
        self.messages: list[mail.ReminderMessage] = []
        self.fail: dict[str, Exception] = {}
        self.lock = threading.Lock()

    def __call__(self, message: mail.ReminderMessage) -> None:
        error = self.fail.get(message.to)
        if error is not None:
            raise error
        with self.lock:
            self.messages.append(message)

    def to(self, account) -> list[mail.ReminderMessage]:
        return [m for m in self.messages if m.to == account.email]


@pytest.fixture
def sent(monkeypatch, require_db) -> Sent:
    box = Sent()
    monkeypatch.setattr(mail, "send_reminder", box)
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "public_base_url", "https://app.example.test")
    return box


@pytest.fixture
def session(require_db):
    with SessionLocal() as s:
        yield s


def run_day(session, accounts, now=NOW) -> list[str]:
    """What the scheduled job does for these accounts: claim, then deliver each claimed email once."""
    report = reminders.plan(session, now, accounts=accounts)
    return [reminders.deliver(session, email_id, now) for email_id in report["emails"]]


def claims(session, account) -> list[tuple[str, date, int]]:
    rows = session.execute(
        select(ReminderDelivery.record_key, ReminderDelivery.deadline, ReminderDelivery.lead_days)
        .where(ReminderDelivery.account_id == account.id)
        .order_by(ReminderDelivery.deadline, ReminderDelivery.lead_days)
    ).all()
    return [tuple(row) for row in rows]


def emails(session, account) -> list[ReminderEmail]:
    session.expire_all()
    return list(
        session.scalars(
            select(ReminderEmail).where(ReminderEmail.account_id == account.id).order_by(ReminderEmail.created_at)
        )
    )


# --- arithmetic ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instant, expected",
    [
        # 23:59:59 on 30 November in Beijing: still the 30th, seven days before 7 December.
        (datetime(2026, 11, 30, 15, 59, 59, tzinfo=UTC), 7),
        # One second later it is 1 December in Beijing, while UTC is still on the 30th.
        (datetime(2026, 11, 30, 16, 0, 0, tzinfo=UTC), 6),
        # Early morning of the deadline day in Beijing is the evening before in UTC.
        (datetime(2026, 12, 6, 16, 0, 0, tzinfo=UTC), 0),
        (datetime(2026, 12, 7, 15, 59, 59, tzinfo=UTC), 0),
        (datetime(2026, 12, 7, 16, 0, 0, tzinfo=UTC), -1),
    ],
)
def test_days_left_is_counted_between_beijing_dates(instant, expected):
    today = reminders.beijing_date(instant)
    assert reminders.days_left(date(2026, 12, 7), today) == expected


def test_a_naive_instant_is_refused():
    with pytest.raises(ValueError):
        reminders.beijing_date(datetime(2026, 11, 30, 16, 0, 0))


@pytest.mark.parametrize(
    "left, expected",
    [
        (15, None),
        (14, 14),
        (13, 14),  # the 14-day reminder, one day late
        (12, 14),  # two days late: the last day it may still go out
        (11, None),  # three days late: dropped
        (8, None),
        (7, 7),
        (6, 7),
        (5, 7),
        (4, None),
        (3, 3),
        (2, 3),
        (1, 1),
        (0, 1),  # the deadline day itself: only as the missed one-day reminder
        (-1, None),
    ],
)
def test_the_lead_time_that_is_due(left, expected):
    assert reminders.due_lead(left, (14, 7, 3, 1)) == expected


def test_only_the_nearest_lead_time_is_ever_due():
    # Seven days was missed and three days has come: the three-day reminder is due, never both.
    assert reminders.due_lead(3, (14, 7, 3, 1)) == 3
    # Adjacent lead times: the later one supersedes the earlier inside its catch-up window.
    assert reminders.due_lead(2, (3, 2, 1)) == 2
    assert reminders.due_lead(0, (2,)) == 2
    assert reminders.due_lead(0, ()) is None


# --- what is due ---------------------------------------------------------------------------------


def test_a_reminder_is_sent_once_for_a_deadline_seven_days_away(sent, session):
    account = make_account(session)
    record = add_record(session, account, 7, round="Round 1", source_url="https://example.edu/apply")

    assert run_day(session, [account]) == ["sent"]
    assert claims(session, account) == [(record.id, record.deadline, 7)]
    assert len(sent.to(account)) == 1

    # A rerun the same day, and a second delivery of the same email, send nothing more.
    assert run_day(session, [account]) == []
    assert reminders.deliver(session, emails(session, account)[0].id, NOW) == "not pending"
    assert len(sent.to(account)) == 1


@pytest.mark.parametrize(
    "status, reminded",
    [
        ("considering", True),
        ("applying", True),
        ("submitted", False),
        ("offered", False),
        ("rejected", False),
        ("excluded", False),
    ],
)
def test_only_applications_still_being_prepared_are_reminded(sent, session, status, reminded):
    account = make_account(session)
    add_record(session, account, 3, status=status)
    run_day(session, [account])
    assert len(sent.to(account)) == (1 if reminded else 0)


def test_unknown_past_and_distant_deadlines_get_no_reminder(sent, session):
    account = make_account(session)
    add_record(session, account, None)
    add_record(session, account, -1)
    add_record(session, account, 10)
    add_record(session, account, 30)
    assert run_day(session, [account]) == []
    assert claims(session, account) == []
    assert sent.messages == []


def test_an_anonymous_subject_is_never_mailed(sent, session):
    # The planner walks accounts; a subject without one has no address to write to.
    client = Client(id=str(uuid.uuid4()))
    session.add(client)
    session.commit()
    session.add(
        ApplicationPlan(
            id=str(uuid.uuid4()), client_id=client.id, school="S", name="N", status="applying",
            deadline=TODAY + timedelta(days=7), deadline_override=True, materials_ready=False, material_notes="",
        )
    )
    session.commit()
    report = reminders.plan(session, NOW, accounts=[])
    assert report["emails"] == []
    assert sent.messages == []


def test_the_job_does_nothing_when_login_mode_is_off(sent, session, monkeypatch):
    account = make_account(session)
    add_record(session, account, 7)
    monkeypatch.setattr(settings, "auth_enabled", False)
    report = reminders.plan(session, NOW, accounts=[account])
    assert report["emails"] == [] and "skipped" in report
    assert claims(session, account) == []


def test_a_catalogue_application_is_reminded_by_its_record_key(sent, session):
    from app.models.application import Application
    from app.seed import seed_programs
    from tests.test_seed import PROGRAM_IDS

    seed_programs(session)
    session.commit()
    account = make_account(session)
    program_id = sorted(PROGRAM_IDS)[0]
    session.add(
        Application(
            id=str(uuid.uuid4()), client_id=account.client_id, program_id=program_id, tier="稳",
            status="applying", official_deadline=TODAY + timedelta(days=3),
            deadline_source_url="https://example.edu/dates",
        )
    )
    session.commit()

    assert run_day(session, [account]) == ["sent"]
    assert claims(session, account) == [(f"catalog:{program_id}", TODAY + timedelta(days=3), 3)]
    assert "https://example.edu/dates" in sent.to(account)[0].text


# --- re-arm, catch-up, cap, digest ---------------------------------------------------------------


def test_a_changed_deadline_is_a_new_reminder(sent, session, monkeypatch):
    monkeypatch.setattr(settings, "reminder_daily_cap", 5)
    account = make_account(session)
    record = add_record(session, account, 7)
    assert run_day(session, [account]) == ["sent"]

    # The applicant moves the deadline a week out; a week later it is seven days away again.
    first = record.deadline
    record.deadline = first + timedelta(days=7)
    session.commit()
    later = NOW + timedelta(days=7)
    assert run_day(session, [account], later) == ["sent"]
    assert claims(session, account) == [(record.id, first, 7), (record.id, first + timedelta(days=7), 7)]
    assert len(sent.to(account)) == 2

    # Moved away and back to a date already reminded at this lead time: nothing more is sent.
    record.deadline = first + timedelta(days=30)
    session.commit()
    assert run_day(session, [account], later + timedelta(hours=1)) == []
    record.deadline = first + timedelta(days=7)
    session.commit()
    assert run_day(session, [account], later + timedelta(hours=2)) == []
    assert len(sent.to(account)) == 2


def test_a_missed_day_is_caught_up_once_and_states_the_days_actually_left(sent, session):
    account = make_account(session)
    record = add_record(session, account, 7)
    # The worker was down on the seventh day; the job next runs the day after.
    assert run_day(session, [account], NOW + timedelta(days=1)) == ["sent"]
    assert claims(session, account) == [(record.id, record.deadline, 7)]
    text = sent.to(account)[0].text
    assert "还有 6 天" in text and "还有 7 天" not in text


def test_a_long_outage_does_not_send_stale_reminders_or_a_burst(sent, session):
    account = make_account(session)
    record = add_record(session, account, 14)
    # Down from before the 14-day mark until four days before the deadline: 14 and 7 are both
    # missed, 7 by three days. Nothing goes out for them.
    assert run_day(session, [account], NOW + timedelta(days=10)) == []
    assert sent.messages == []
    # The next lead time is sent on its own day, alone.
    assert run_day(session, [account], NOW + timedelta(days=11)) == ["sent"]
    assert claims(session, account) == [(record.id, record.deadline, 3)]
    assert len(sent.to(account)) == 1


def test_several_reminders_for_one_applicant_go_in_one_email(sent, session):
    account = make_account(session)
    names = ["MSc Alpha", "MSc Beta", "MSc Gamma"]
    for name, days in zip(names, (1, 3, 14)):
        add_record(session, account, days, name=name)
    add_record(session, account, 30, name="MSc Far")

    assert run_day(session, [account]) == ["sent"]
    [message] = sent.to(account)
    for name in names:
        assert name in message.text and name in message.html
    assert "MSc Far" not in message.text
    # Nearest deadline first.
    assert message.text.index("MSc Alpha") < message.text.index("MSc Beta") < message.text.index("MSc Gamma")
    assert len(claims(session, account)) == 3
    assert len(emails(session, account)) == 1


def test_the_daily_cap_holds_back_a_second_email_until_the_next_day(sent, session, monkeypatch):
    monkeypatch.setattr(settings, "reminder_daily_cap", 1)
    account = make_account(session)
    add_record(session, account, 7, name="MSc First")
    assert run_day(session, [account]) == ["sent"]

    # Later the same day another application becomes due; a rerun may not send a second email.
    late = add_record(session, account, 3, name="MSc Second")
    assert run_day(session, [account], NOW + timedelta(hours=3)) == []
    assert len(sent.to(account)) == 1
    assert (late.id, late.deadline, 3) not in claims(session, account)

    # The next day's run catches it up, with the days actually left.
    assert run_day(session, [account], NOW + timedelta(days=1)) == ["sent"]
    assert "MSc Second" in sent.to(account)[1].text and "还有 2 天" in sent.to(account)[1].text


def test_a_higher_cap_allows_that_many_emails_a_day(sent, session, monkeypatch):
    monkeypatch.setattr(settings, "reminder_daily_cap", 2)
    account = make_account(session)
    add_record(session, account, 7)
    assert run_day(session, [account]) == ["sent"]
    add_record(session, account, 3)
    assert run_day(session, [account], NOW + timedelta(hours=1)) == ["sent"]
    add_record(session, account, 1)
    assert run_day(session, [account], NOW + timedelta(hours=2)) == []
    assert len(sent.to(account)) == 2


# --- once only, under concurrency ----------------------------------------------------------------


def test_workers_planning_the_same_account_together_claim_each_reminder_once(sent, session):
    for _ in range(ROUNDS):
        account = make_account(session)
        for days in (1, 3, 7):
            add_record(session, account, days)

        account_id = account.id

        def plan_once():
            with SessionLocal() as own:
                return reminders.plan(own, NOW, accounts=[own.get(Account, account_id)])["emails"]

        planned = [ids for ids in at_once(*[plan_once] * WORKERS) if ids]
        assert len(planned) == 1, f"expected one worker to claim, got {len(planned)}"
        assert len(claims(session, account)) == 3
        assert len(emails(session, account)) == 1


def test_the_unique_claim_alone_stops_a_second_worker_that_skipped_the_lock(sent, session):
    # The account lock is what keeps a day's reminders in one email; the unique constraint is what
    # makes a reminder impossible to claim twice even for a writer that never took the lock.
    for _ in range(ROUNDS):
        account = make_account(session)
        record = add_record(session, account, 7)
        item = reminders.Due(record_key=record.id, deadline=record.deadline, lead_days=7)
        account_id = account.id

        def claim_once():
            with SessionLocal() as own:
                email = ReminderEmail(
                    id=str(uuid.uuid4()), account_id=account_id, send_date=TODAY, status="pending", items=[]
                )
                own.add(email)
                own.flush()
                won = reminders.claim(own, account_id, email.id, [item])
                if won:
                    own.commit()
                else:
                    own.rollback()
                return len(won)

        assert sorted(at_once(*[claim_once] * WORKERS)) == [0] * (WORKERS - 1) + [1]
        assert len(claims(session, account)) == 1
        assert len(emails(session, account)) == 1


def test_workers_delivering_the_same_email_together_send_it_once(sent, session):
    for _ in range(ROUNDS):
        account = make_account(session)
        add_record(session, account, 7)
        [email_id] = reminders.plan(session, NOW, accounts=[account])["emails"]

        def deliver_once():
            with SessionLocal() as own:
                return reminders.deliver(own, email_id, NOW)

        results = at_once(*[deliver_once] * WORKERS)
        assert sorted(results) == ["not pending"] * (WORKERS - 1) + ["sent"]
        assert len(sent.to(account)) == 1
        [email] = emails(session, account)
        assert email.status == "sent" and email.attempts == 1


def test_a_task_delivered_again_after_the_send_does_not_send_again(sent, session):
    account = make_account(session)
    add_record(session, account, 7)
    [email_id] = reminders.plan(session, NOW, accounts=[account])["emails"]
    assert reminders.deliver(session, email_id, NOW) == "sent"
    for _ in range(3):
        assert reminders.deliver(session, email_id, NOW) == "not pending"
    assert len(sent.to(account)) == 1


# --- failure and retry ---------------------------------------------------------------------------


def test_a_failed_send_is_recorded_and_retried_with_backoff(sent, session):
    account = make_account(session)
    record = add_record(session, account, 7)
    sent.fail[account.email] = mail.MailError("send failed: SMTPServerDisconnected")
    [email_id] = reminders.plan(session, NOW, accounts=[account])["emails"]

    assert reminders.deliver(session, email_id, NOW) == "retry"
    [email] = emails(session, account)
    assert (email.status, email.attempts) == ("retry", 1)
    assert email.last_error == "MailError"
    # The claim stays while a retry is pending, so nothing else can mail this reminder meanwhile.
    assert claims(session, account) == [(record.id, record.deadline, 7)]

    del sent.fail[account.email]
    assert reminders.deliver(session, email_id, NOW + timedelta(minutes=1)) == "sent"
    [email] = emails(session, account)
    assert (email.status, email.attempts) == ("sent", 2)
    assert len(sent.to(account)) == 1


def test_the_backoff_grows_and_stops():
    delays = [reminders.backoff_delay(attempt) for attempt in range(1, reminders.MAX_ATTEMPTS)]
    assert delays == sorted(delays) and delays[0] >= 60 and len(set(delays)) == len(delays)


def test_an_address_that_keeps_failing_is_given_up_and_does_not_block_others(sent, session):
    broken, fine = make_account(session), make_account(session)
    record = add_record(session, broken, 7)
    add_record(session, fine, 7)
    sent.fail[broken.email] = mail.MailError("send failed: SMTPRecipientsRefused")

    report = reminders.plan(session, NOW, accounts=[broken, fine])
    results = {email_id: reminders.deliver(session, email_id, NOW) for email_id in report["emails"]}
    assert sorted(results.values()) == ["retry", "sent"]
    assert len(sent.to(fine)) == 1

    [email] = emails(session, broken)
    for _ in range(reminders.MAX_ATTEMPTS - 1):
        last = reminders.deliver(session, email.id, NOW + timedelta(minutes=30))
    assert last == "failed"
    [email] = emails(session, broken)
    assert (email.status, email.attempts) == ("failed", reminders.MAX_ATTEMPTS)
    assert email.last_error == "MailError"
    # What it would have said stays on the record of the failure; the claim is released.
    assert email.items == [{"recordKey": record.id, "deadline": record.deadline.isoformat(), "leadDays": 7}]
    assert claims(session, broken) == []
    assert reminders.deliver(session, email.id, NOW + timedelta(hours=1)) == "not pending"

    # The next day the reminder is still inside its catch-up window and gets a fresh email.
    del sent.fail[broken.email]
    assert run_day(session, [broken], NOW + timedelta(days=1)) == ["sent"]
    assert "还有 6 天" in sent.to(broken)[0].text


def test_an_error_inside_one_account_does_not_stop_the_plan_for_the_next(sent, session, monkeypatch):
    first, second = make_account(session), make_account(session)
    add_record(session, first, 7)
    add_record(session, second, 7)
    real = reminders.plan_account

    def flaky(own, account, today):
        if account.id == first.id:
            raise RuntimeError("boom")
        return real(own, account, today)

    monkeypatch.setattr(reminders, "plan_account", flaky)
    report = reminders.plan(session, NOW, accounts=[first, second])
    assert len(report["emails"]) == 1 and report["errors"] == 1
    assert claims(session, first) == [] and len(claims(session, second)) == 1


def test_a_failure_before_the_mail_server_is_reached_is_retried_not_left_sending(sent, session, monkeypatch):
    account = make_account(session)
    record = add_record(session, account, 7)
    [email_id] = reminders.plan(session, NOW, accounts=[account])["emails"]
    real = reminders._entries

    def broken(*args, **kwargs):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(reminders, "_entries", broken)
    assert reminders.deliver(session, email_id, NOW) == "retry"
    [email] = emails(session, account)
    assert (email.status, email.attempts, email.last_error) == ("retry", 1, "RuntimeError")
    assert claims(session, account) == [(record.id, record.deadline, 7)]
    assert sent.messages == []

    monkeypatch.setattr(reminders, "_entries", real)
    assert reminders.deliver(session, email_id, NOW) == "sent"
    assert len(sent.to(account)) == 1


def test_a_name_with_a_line_break_is_mailed_on_one_line(session, require_db, monkeypatch):
    # The form cannot enter one, but the API accepts it; in a Subject it would end the header early.
    _smtp_settings(monkeypatch)
    account = make_account(session)
    add_record(session, account, 7, school="MIT\nEECS", name="MEng\r\nBcc: someone@example.test")
    assert run_day(session, [account]) == ["sent"]
    [raw] = FakeSMTP.delivered
    message = message_from_bytes(raw, policy=policy.default)
    assert message["Bcc"] is None
    assert "MIT EECS MEng Bcc: someone@example.test" in message["Subject"]
    assert "MIT EECS · MEng Bcc: someone@example.test" in message.get_body(("plain",)).get_content()


def test_a_message_that_cannot_be_built_counts_as_not_sent(session, require_db, monkeypatch):
    _smtp_settings(monkeypatch)
    monkeypatch.setattr(mail, "reminder_mime", lambda message: (_ for _ in ()).throw(ValueError("bad header")))
    account = make_account(session)
    add_record(session, account, 7)
    assert run_day(session, [account]) == ["retry"]
    assert emails(session, account)[0].last_error == "MailError(ValueError)"
    assert FakeSMTP.delivered == []


def test_a_send_that_may_have_gone_out_is_not_retried(sent, session):
    account = make_account(session)
    record = add_record(session, account, 7)
    sent.fail[account.email] = mail.MailUncertain("no answer after the message was handed over")
    [email_id] = reminders.plan(session, NOW, accounts=[account])["emails"]

    assert reminders.deliver(session, email_id, NOW) == "uncertain"
    assert reminders.deliver(session, email_id, NOW) == "not pending"
    # At most once: the claim is kept, so neither a rerun nor tomorrow's catch-up mails it again.
    assert claims(session, account) == [(record.id, record.deadline, 7)]
    assert run_day(session, [account], NOW + timedelta(days=1)) == []


def test_an_email_never_attempted_on_its_day_expires_and_is_planned_again(sent, session):
    account = make_account(session)
    record = add_record(session, account, 7)
    [email_id] = reminders.plan(session, NOW, accounts=[account])["emails"]

    # The broker lost the task. The next day's plan expires the stale email, releases its claims
    # and plans the reminder again, so the text is written for the day it is sent.
    tomorrow = NOW + timedelta(days=1)
    assert reminders.deliver(session, email_id, tomorrow) == "expired"
    assert claims(session, account) == []
    assert run_day(session, [account], tomorrow) == ["sent"]
    assert claims(session, account) == [(record.id, record.deadline, 7)]
    assert [e.status for e in emails(session, account)] == ["expired", "sent"]


def test_the_plan_sweeps_yesterdays_unfinished_emails(sent, session):
    pending, stuck = make_account(session), make_account(session)
    add_record(session, pending, 7)
    stuck_record = add_record(session, stuck, 7)
    reminders.plan(session, NOW, accounts=[pending, stuck])
    # One worker died between taking the attempt and recording its outcome.
    [email] = emails(session, stuck)
    email.status, email.attempts = "sending", 1
    session.commit()

    tomorrow = NOW + timedelta(days=1)
    report = reminders.plan(session, tomorrow, accounts=[pending, stuck])
    assert emails(session, pending)[0].status == "expired"
    # A send cut off mid-way may have gone out: it is closed as uncertain and keeps its claim.
    assert emails(session, stuck)[0].status == "uncertain"
    assert claims(session, stuck) == [(stuck_record.id, stuck_record.deadline, 7)]
    assert len(report["emails"]) == 1  # only the expired one is planned again


def test_a_rerun_the_same_day_hands_back_emails_still_waiting(sent, session):
    account = make_account(session)
    add_record(session, account, 7)
    [email_id] = reminders.plan(session, NOW, accounts=[account])["emails"]
    again = reminders.plan(session, NOW + timedelta(hours=1), accounts=[account])
    assert again["emails"] == [] and again["waiting"] == [email_id]


# --- the record at the moment of sending -----------------------------------------------------------


def test_a_record_changed_after_the_claim_is_not_mailed_as_it_was(sent, session):
    account = make_account(session)
    moved = add_record(session, account, 7, name="MSc Moved")
    closed = add_record(session, account, 7, name="MSc Submitted")
    kept = add_record(session, account, 7, name="MSc Kept")
    [email_id] = reminders.plan(session, NOW, accounts=[account])["emails"]

    moved.deadline = moved.deadline + timedelta(days=30)
    closed.status = "submitted"
    session.commit()
    assert reminders.deliver(session, email_id, NOW) == "sent"
    [message] = sent.to(account)
    assert "MSc Kept" in message.text
    assert "MSc Moved" not in message.text and "MSc Submitted" not in message.text
    assert kept.deadline.isoformat() in message.text


def test_nothing_is_sent_when_reminders_were_turned_off_after_the_claim(sent, session):
    account = make_account(session)
    add_record(session, account, 7)
    [email_id] = reminders.plan(session, NOW, accounts=[account])["emails"]
    row = reminders.settings_for(session, account.id)
    row.enabled = False
    session.commit()
    assert reminders.deliver(session, email_id, NOW) == "cancelled"
    assert sent.messages == []


def test_an_account_with_reminders_off_is_not_planned(sent, session):
    account = make_account(session)
    add_record(session, account, 7)
    row = reminders.settings_for(session, account.id)
    row.enabled = False
    session.commit()
    assert run_day(session, [account]) == []
    assert claims(session, account) == []


def test_the_applicants_own_lead_times_are_used(sent, session):
    account = make_account(session)
    add_record(session, account, 7, name="MSc Seven")
    add_record(session, account, 10, name="MSc Ten")
    row = reminders.settings_for(session, account.id)
    row.lead_days = [10]
    session.commit()
    assert run_day(session, [account]) == ["sent"]
    [message] = sent.to(account)
    assert "MSc Ten" in message.text and "MSc Seven" not in message.text


# --- what the email says -------------------------------------------------------------------------


def test_the_email_states_the_record_and_nothing_else(sent, session):
    account = make_account(session)
    checked = add_record(
        session, account, 7, school="Checked University", name="MSc Checked", round="Round 2",
        source_url="https://checked.example.edu/deadlines?x=1&y=2",
        checked_at=datetime(2026, 11, 10, 18, 30, tzinfo=UTC),
    )
    add_record(session, account, 3, school="Bare University", name="MSc <Bare> & Co")

    assert run_day(session, [account]) == ["sent"]
    [message] = sent.to(account)
    text = message.text

    # The date as stored, the round, the source and the applicant's check, for the record that has them.
    assert checked.deadline.isoformat() in text
    assert "Round 2" in text
    assert "https://checked.example.edu/deadlines?x=1&y=2" in text
    # 18:30 UTC on the 10th is the 11th in Beijing.
    assert "2026-11-11" in text and "核对过" in text
    # The record without them says so instead of filling the gap.
    bare = text[text.index("Bare University"):]
    assert "没有核对" in bare.split("Checked University")[0]
    assert "没有填来源" in bare.split("Checked University")[0]
    # The applicant is sent to the official page for the time and the zone.
    assert "官网" in text and "时区" in text

    # No time of day and no zone is stated anywhere: the record has neither.
    for part in (text, message.html):
        # Links aside: the token is random text and the source is the applicant's own.
        prose = re.sub(r"https?://\S+", "", part)
        assert not re.search(r"\d{1,2}[:：]\d{2}", prose)
        assert not re.search(r"UTC|GMT|EST|PST|午夜|零点|凌晨|上午|下午|晚上", prose)
    # The only links are the stored source, the application list, settings and the unsubscribe page.
    links = set(re.findall(r"https?://[^\s\"<>）)]+", text))
    assert links == {
        "https://checked.example.edu/deadlines?x=1&y=2",
        "https://app.example.test/applications",
        message.unsubscribe_page,
    }
    # That link lands on a page that asks first, and the copy says so: a mail gateway that opens
    # every link must not be able to unsubscribe anyone.
    for part in (text, message.html):
        assert "确认退订" in part and "就会退订" not in part
    assert message.subject.startswith("申请截止提醒")


def test_the_html_part_is_escaped_and_loads_nothing_remote(sent, session):
    account = make_account(session)
    add_record(
        session, account, 3, school="Bare University", name="MSc <Bare> & Co",
        source_url="https://example.edu/a?x=1&y=2",
    )
    run_day(session, [account])
    html = sent.to(account)[0].html
    assert "MSc &lt;Bare&gt; &amp; Co" in html and "<Bare>" not in html
    assert 'href="https://example.edu/a?x=1&amp;y=2"' in html
    lowered = html.lower()
    for forbidden in ("<img", "<script", "<link", "<iframe", "src=", "url(", "@import", "<form"):
        assert forbidden not in lowered


def test_a_collected_date_is_called_collected_and_unchecked(sent, session):
    from app.models.application import Application
    from app.models.program import ProgramDeadline
    from app.services import application_records

    # Any program the catalogue holds a collected date for; the record then reads that date.
    program_id = session.scalar(select(ProgramDeadline.program_id).limit(1))
    if program_id is None:
        pytest.skip("the catalogue has no collected deadline")
    account = make_account(session)
    session.add(
        Application(id=str(uuid.uuid4()), client_id=account.client_id, program_id=program_id, tier="稳",
                    status="applying")
    )
    session.commit()
    record = application_records.read_record(session, account.client_id, f"catalog:{program_id}")
    assert record["deadlineOrigin"] == "collected" and record["checkedAt"] is None
    day = record["deadline"]
    # Run on the day that makes the catalogue's own date seven days away.
    now = datetime(day.year, day.month, day.day, 1, 7, tzinfo=UTC) - timedelta(days=7)
    assert run_day(session, [account], now) == ["sent"]
    text = sent.to(account)[0].text
    assert day.isoformat() in text and "学校库" in text and "没有核对" in text
    assert record["sourceUrl"] in text


def test_the_smtp_message_carries_both_parts_and_the_unsubscribe_headers(session, require_db, monkeypatch):
    account, delivered = _through_fake_smtp(session, monkeypatch)
    [raw] = delivered
    message = message_from_bytes(raw, policy=policy.default)
    assert message["To"] == account.email
    assert message["From"] == "sender@example.test"
    target = message["List-Unsubscribe"]
    assert target.startswith("<https://app.example.test/api/reminders/unsubscribe?token=") and target.endswith(">")
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    kinds = [part.get_content_type() for part in message.walk() if not part.is_multipart()]
    assert kinds == ["text/plain", "text/html"]
    assert "申请截止提醒" in message["Subject"]


# --- logs ----------------------------------------------------------------------------------------

SMTP_SECRET = "smtp-secret-do-not-log-4f1c"


class FakeSMTP:
    """An implicit-TLS SMTP server double: records what it is handed, or fails where told."""

    delivered: list[bytes] = []
    fail_at: str | None = None

    def __init__(self, host, port, timeout=None):
        if FakeSMTP.fail_at == "connect":
            raise OSError(f"connect failed (password {SMTP_SECRET})")

    def login(self, user, password):
        assert password == SMTP_SECRET
        if FakeSMTP.fail_at == "login":
            raise smtplib.SMTPAuthenticationError(535, f"bad credentials {password}".encode())

    def send_message(self, message):
        if FakeSMTP.fail_at == "refused":
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no such user")})
        if FakeSMTP.fail_at == "dropped":
            raise smtplib.SMTPServerDisconnected(f"lost while sending to {message['To']}")
        FakeSMTP.delivered.append(message.as_bytes())

    def quit(self):
        pass

    def close(self):
        pass


def _smtp_settings(monkeypatch):
    FakeSMTP.delivered, FakeSMTP.fail_at = [], None
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "mail_backend", "smtp")
    monkeypatch.setattr(settings, "mail_from", "sender@example.test")
    monkeypatch.setattr(settings, "smtp_user", "sender@example.test")
    monkeypatch.setattr(settings, "smtp_password", SMTP_SECRET)
    monkeypatch.setattr(settings, "public_base_url", "https://app.example.test")


def _through_fake_smtp(session, monkeypatch, fail_at=None):
    _smtp_settings(monkeypatch)
    FakeSMTP.fail_at = fail_at
    account = make_account(session)
    add_record(session, account, 7, source_url="https://example.edu/apply")
    run_day(session, [account])
    return account, FakeSMTP.delivered


@pytest.mark.parametrize("fail_at, status", [
    (None, "sent"), ("connect", "retry"), ("login", "retry"), ("refused", "retry"), ("dropped", "uncertain"),
])
def test_the_token_the_address_and_the_smtp_password_never_reach_the_logs(
    session, require_db, monkeypatch, caplog, fail_at, status
):
    caplog.set_level(logging.DEBUG)
    # The test client's own request log is not the server's.
    for name in ("httpx", "httpx2"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", True)
    account, _ = _through_fake_smtp(session, monkeypatch, fail_at)
    [email] = emails(session, account)
    assert email.status == status
    token = reminders.unsubscribe_token(reminders.settings_for(session, account.id))

    # Unsubscribing over HTTP, by the header's URL and by the page's request, logs neither.
    client = new_client()
    assert client.post(f"/api/reminders/unsubscribe?token={token}").status_code == 200
    assert client.post("/api/reminders/unsubscribe", json={"token": token}).status_code == 200
    assert client.post("/api/reminders/unsubscribe?token=bad.token").status_code == 400

    logged = caplog.text + "".join(str(record.args) for record in caplog.records)
    assert reminders.__name__ in {record.name for record in caplog.records}, "the job should log something"
    for secret in (token, token.split(".")[1], SMTP_SECRET, account.email, account.email.split("@")[0]):
        assert secret not in logged
    assert SMTP_SECRET not in (email.last_error or "") and account.email not in (email.last_error or "")


def test_the_access_log_line_of_an_unsubscribe_request_has_no_token():
    from app.logs import RedactUnsubscribeToken

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "POST", "/api/reminders/unsubscribe?token=abc.DEF-ghi_123&x=1", "1.1", 200), None,
    )
    assert RedactUnsubscribeToken().filter(record) is True
    line = record.getMessage()
    assert "abc.DEF-ghi_123" not in line and "/api/reminders/unsubscribe?token=[redacted]&x=1" in line

    other = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/api/programs?token=keep", "1.1", 200), None,
    )
    RedactUnsubscribeToken().filter(other)
    assert "token=keep" in other.getMessage()


def test_the_log_backend_refuses_to_run_in_production(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "log")
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(mail.MailError):
        mail.send_reminder(
            mail.ReminderMessage(to="a@example.test", subject="s", text="t", html="<p>t</p>",
                                 unsubscribe_url="https://x/u", unsubscribe_page="https://x/p", reference="r")
        )


# --- unsubscribe token ---------------------------------------------------------------------------


def _flip(char: str) -> str:
    return "A" if char != "A" else "B"


def test_the_link_turns_reminders_off_without_signing_in(login_mode, session):
    client = new_client()
    email = login(client, login_mode)["account"]["email"]
    account = session.scalar(select(Account).where(Account.email == email))
    token = reminders.unsubscribe_token(reminders.settings_for(session, account.id))
    session.commit()

    anonymous = new_client()
    response = anonymous.post("/api/reminders/unsubscribe", json={"token": token})
    assert response.status_code == 200 and response.json() == {"unsubscribed": True}
    # Nothing about the account comes back, and no cookie is set: the link is not a way in.
    assert email not in response.text and not response.cookies
    assert anonymous.get("/api/reminders/settings").status_code == 401
    anonymous.cookies.set("leapashore_session", token)
    assert anonymous.get("/api/reminders/settings").status_code == 401
    assert anonymous.get("/api/application-records").status_code == 401

    state = client.get("/api/reminders/settings").json()
    assert state["enabled"] is False and state["unsubscribedAt"]


def test_using_the_link_again_changes_nothing_more(login_mode, session):
    client = new_client()
    email = login(client, login_mode)["account"]["email"]
    account = session.scalar(select(Account).where(Account.email == email))
    token = reminders.unsubscribe_token(reminders.settings_for(session, account.id))
    session.commit()

    assert new_client().post("/api/reminders/unsubscribe", json={"token": token}).status_code == 200
    first = client.get("/api/reminders/settings").json()
    assert new_client().post(f"/api/reminders/unsubscribe?token={token}").status_code == 200
    assert client.get("/api/reminders/settings").json() == first

    # Turned back on by the applicant, an older email's link still works: every email's link must.
    on = client.put("/api/reminders/settings", json={"enabled": True, "baseVersion": first["version"]})
    assert on.status_code == 200 and on.json()["enabled"] is True and on.json()["unsubscribedAt"] is None
    assert new_client().post("/api/reminders/unsubscribe", json={"token": token}).status_code == 200
    assert client.get("/api/reminders/settings").json()["enabled"] is False


def test_a_tampered_token_is_refused_and_changes_nothing(sent, session):
    account, other = make_account(session), make_account(session)
    token = reminders.unsubscribe_token(reminders.settings_for(session, account.id))
    other_token = reminders.unsubscribe_token(reminders.settings_for(session, other.id))
    session.commit()
    who, signature = token.split(".")
    other_who, other_signature = other_token.split(".")

    forged = [
        "", "x", "..", token + "x", who, f"{who}.", f".{signature}",
        f"{who}.{signature[:-1]}{_flip(signature[-1])}",
        f"{who}.{_flip(signature[0])}{signature[1:]}",
        # One account's signature does not sign for another, either way round.
        f"{other_who}.{signature}",
        f"{who}.{other_signature}",
        f"{who}.{signature}.{signature}",
        "é.é", "%00.%00", "A" * 5000,
    ]
    client = new_client()
    for candidate in forged:
        assert reminders.unsubscribe(session, candidate) is False, candidate
        response = client.post("/api/reminders/unsubscribe", json={"token": candidate})
        assert response.status_code == 400, candidate
    session.expire_all()
    assert reminders.settings_for(session, account.id).enabled is True
    assert reminders.settings_for(session, other.id).enabled is True

    # A's link turns off A only.
    assert reminders.unsubscribe(session, token) is True
    session.expire_all()
    assert reminders.settings_for(session, account.id).enabled is False
    assert reminders.settings_for(session, other.id).enabled is True


def test_a_token_of_a_deleted_account_is_refused(sent, session):
    account = make_account(session)
    account_id = account.id
    token = reminders.unsubscribe_token(reminders.settings_for(session, account_id))
    session.commit()
    session.delete(session.get(Client, account.client_id))
    session.commit()
    session.expunge_all()
    assert reminders.unsubscribe(session, token) is False
    assert session.scalar(select(func.count()).select_from(ReminderSettings).where(
        ReminderSettings.account_id == account_id)) == 0


def test_opening_the_headers_url_in_a_browser_changes_nothing(login_mode, session):
    client = new_client()
    email = login(client, login_mode)["account"]["email"]
    account = session.scalar(select(Account).where(Account.email == email))
    token = reminders.unsubscribe_token(reminders.settings_for(session, account.id))
    session.commit()
    # A GET (a link scanner, a mail client treating the header as a link) only leads to the page.
    response = new_client().get(f"/api/reminders/unsubscribe?token={token}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/reminders/unsubscribe?token={token}"
    assert client.get("/api/reminders/settings").json()["enabled"] is True


# --- settings API --------------------------------------------------------------------------------


def test_settings_need_a_signed_in_account(login_mode):
    client = new_client()
    assert client.get("/api/reminders/settings").status_code == 401
    assert client.put("/api/reminders/settings", json={"enabled": False, "baseVersion": "1"}).status_code == 401


def test_reminders_are_on_by_default_at_14_7_3_and_1_days(login_mode):
    client = new_client()
    login(client, login_mode)
    state = client.get("/api/reminders/settings").json()
    assert state["enabled"] is True
    assert state["leadDays"] == [14, 7, 3, 1]
    assert state["unsubscribedAt"] is None
    assert isinstance(state["version"], str) and state["version"]
    assert "unsubscribeKey" not in state and "key" not in "".join(state).lower()


def test_an_update_states_its_base_version_and_a_stale_one_is_refused(login_mode):
    phone = new_client()
    login(phone, login_mode)
    laptop = second_device(phone)
    seen = phone.get("/api/reminders/settings").json()

    missing = phone.put("/api/reminders/settings", json={"leadDays": [7]})
    assert missing.status_code == 422

    first = phone.put("/api/reminders/settings", json={"leadDays": [7, 2], "baseVersion": seen["version"]})
    assert first.status_code == 200, first.text
    assert first.json()["leadDays"] == [7, 2] and first.json()["version"] != seen["version"]

    stale = laptop.put("/api/reminders/settings", json={"enabled": False, "baseVersion": seen["version"]})
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "stale_version" and body["current"] == first.json()
    assert laptop.get("/api/reminders/settings").json() == first.json()

    # Keeping one's own change is the same request against the version the refusal returned.
    kept = laptop.put(
        "/api/reminders/settings", json={"enabled": False, "baseVersion": body["current"]["version"]}
    )
    assert kept.status_code == 200 and kept.json()["enabled"] is False and kept.json()["leadDays"] == [7, 2]


def test_two_devices_saving_together_get_one_accepted_and_one_refused(login_mode):
    phone = new_client()
    login(phone, login_mode)
    laptop = second_device(phone)
    for round_number in range(ROUNDS):
        seen = phone.get("/api/reminders/settings").json()
        responses = at_once(
            # Each round writes values the row does not hold: restating a row does not move its version.
            lambda: phone.put(
                "/api/reminders/settings", json={"leadDays": [10 + round_number], "baseVersion": seen["version"]}
            ),
            lambda: laptop.put(
                "/api/reminders/settings", json={"leadDays": [50 + round_number], "baseVersion": seen["version"]}
            ),
        )
        codes = sorted(r.status_code for r in responses)
        assert codes == [200, 409], f"round {round_number}: {codes}"
        winner = next(r for r in responses if r.status_code == 200).json()
        assert phone.get("/api/reminders/settings").json() == winner


@pytest.mark.parametrize(
    "lead_days",
    [[], [0], [-1], [91], [7, 7], [1, 2, 3, 4, 5, 6, 7], ["7"], [1.5], None, "7", [True]],
)
def test_lead_times_that_make_no_sense_are_refused(login_mode, lead_days):
    client = new_client()
    login(client, login_mode)
    seen = client.get("/api/reminders/settings").json()
    response = client.put("/api/reminders/settings", json={"leadDays": lead_days, "baseVersion": seen["version"]})
    assert response.status_code == 422, response.text
    assert client.get("/api/reminders/settings").json() == seen


def test_lead_times_are_stored_longest_first(login_mode):
    client = new_client()
    login(client, login_mode)
    seen = client.get("/api/reminders/settings").json()
    saved = client.put("/api/reminders/settings", json={"leadDays": [1, 30, 7], "baseVersion": seen["version"]})
    assert saved.json()["leadDays"] == [30, 7, 1]


def test_an_unsubscribe_moves_the_version_an_open_settings_page_holds(login_mode, session):
    client = new_client()
    email = login(client, login_mode)["account"]["email"]
    seen = client.get("/api/reminders/settings").json()
    account = session.scalar(select(Account).where(Account.email == email))
    token = reminders.unsubscribe_token(reminders.settings_for(session, account.id))
    session.commit()
    assert new_client().post("/api/reminders/unsubscribe", json={"token": token}).status_code == 200
    stale = client.put("/api/reminders/settings", json={"leadDays": [5], "baseVersion": seen["version"]})
    assert stale.status_code == 409 and stale.json()["current"]["enabled"] is False


def test_settings_are_unavailable_without_login_mode(require_db):
    client = new_client()
    assert client.get("/api/reminders/settings").status_code == 401


# --- preview -------------------------------------------------------------------------------------


def test_the_preview_counts_what_would_be_sent_and_writes_nothing(sent, session):
    account, quiet = make_account(session), make_account(session)
    first = add_record(session, account, 7)
    second = add_record(session, account, 1)
    add_record(session, quiet, 30)

    def counts():
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (ReminderSettings, ReminderEmail, ReminderDelivery)
        )

    before = counts()
    report = reminders.preview(session, NOW, accounts=[account, quiet])
    assert counts() == before and sent.messages == []
    assert report["date"] == "2026-11-20"
    assert report["accounts"] == 2 and report["emails"] == 1 and report["reminders"] == 2
    assert sorted(item["application"] for item in report["items"]) == sorted([first.id, second.id])
    assert {item["leadDays"] for item in report["items"]} == {7, 1}
    rendered = repr(report)
    assert account.email not in rendered and account.id not in rendered and "@" not in rendered

    # After the real run the preview shows nothing left to send.
    run_day(session, [account, quiet])
    after = reminders.preview(session, NOW, accounts=[account, quiet])
    assert after["emails"] == 0 and after["reminders"] == 0


def test_the_preview_sees_what_the_plan_will_release(sent, session):
    account = make_account(session)
    record = add_record(session, account, 7)
    reminders.plan(session, NOW, accounts=[account])
    # The delivery never ran. Tomorrow's plan expires that email and plans the reminder again, and
    # the preview says so beforehand.
    tomorrow = NOW + timedelta(days=1)
    assert reminders.preview(session, NOW, accounts=[account])["reminders"] == 0
    report = reminders.preview(session, tomorrow, accounts=[account])
    assert [item["application"] for item in report["items"]] == [record.id]
    assert emails(session, account)[0].status == "pending"
    assert len(reminders.plan(session, tomorrow, accounts=[account])["emails"]) == 1


def test_a_body_the_parser_cannot_take_is_just_an_invalid_link(require_db):
    client = new_client()
    for body in ("[" * 2000, "{", "", "null", "[1]", '{"token": 5}', "List-Unsubscribe=One-Click"):
        response = client.post("/api/reminders/unsubscribe", content=body, headers={"Content-Type": "text/plain"})
        assert response.status_code == 400, body[:20]


def test_the_command_only_previews(capsys, sent, session, monkeypatch):
    from app import reminders_cli

    monkeypatch.setattr(reminders_cli, "_accounts", lambda own: [])
    assert reminders_cli.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert '"emails": 0' in out and "@" not in out
    with pytest.raises(SystemExit):
        reminders_cli.main([])
    with pytest.raises(SystemExit):
        reminders_cli.main(["--send"])


# --- schedule and schema -------------------------------------------------------------------------


def test_the_beat_runs_the_job_once_a_day_in_beijing_time():
    from app.worker import app as celery_app

    assert celery_app.conf.timezone == "Asia/Shanghai"
    entry = celery_app.conf.beat_schedule["send-deadline-reminders"]
    assert entry["task"] == "reminders.send_due"
    assert entry["schedule"].hour == {9} and entry["schedule"].minute == {7}
    assert {"reminders.send_due", "reminders.deliver"} <= set(celery_app.tasks)


def test_the_migration_only_adds():
    from pathlib import Path

    [path] = Path(__file__).resolve().parent.parent.glob("alembic/versions/*_add_deadline_reminders.py")
    upgrade = path.read_text().split("def upgrade")[1].split("def downgrade")[0]
    assert "create_table" in upgrade
    for forbidden in ("drop_", "alter_column", "add_column", "execute(", "rename"):
        assert forbidden not in upgrade
