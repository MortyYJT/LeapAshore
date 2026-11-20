"""Deadline reminders by email (`docs/product/PRD-multi-device.md`, 3.4).

Three tables, all owned by an account and removed with it:

- `reminder_settings`: whether the account wants reminders and how many days ahead, with the key
  that signs its unsubscribe link. Versioned like every applicant-editable row.
- `reminder_deliveries`: one row per reminder that has been claimed for sending. The unique
  constraint over account, application, deadline date and lead time is the once-only rule: a second
  worker, a retried task or a rerun inserts nothing and therefore mails nothing.
- `reminder_emails`: one row per email (a day's reminders for one account go in one), with its
  attempts and outcome.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.versioning import Versioned


class ReminderSettings(Versioned, Base):
    __tablename__ = "reminder_settings"

    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Days before a deadline, longest first.
    lead_days: Mapped[list[int]] = mapped_column(JSON)
    # 32 random bytes in hex: the HMAC key of this account's unsubscribe link, and of nothing else.
    unsubscribe_key: Mapped[str] = mapped_column(String(64))
    # When the link in an email last turned reminders off; cleared when the applicant turns them on.
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReminderEmail(Base):
    """One email to one account on one Beijing day.

    `status` moves `pending` -> `sending` -> `sent`, or to `retry` (a send that certainly did not go
    out, to be tried again), `failed` (given up; its claims are released), `uncertain` (the send may
    have gone out; never retried), `cancelled` (nothing left to say at send time) or `expired` (not
    sent on its own day; its claims are released).
    """

    __tablename__ = "reminder_emails"
    __table_args__ = (Index("ix_reminder_emails_account_day", "account_id", "send_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id", ondelete="CASCADE"))
    send_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Exception class names only: a server's reply can echo an address or a credential.
    last_error: Mapped[str | None] = mapped_column(String(120))
    # What the email was claimed for: `[{recordKey, deadline, leadDays}]`. Kept after a release.
    items: Mapped[list[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReminderDelivery(Base):
    """The claim on one reminder: this application, this deadline date, this lead time."""

    __tablename__ = "reminder_deliveries"
    __table_args__ = (
        UniqueConstraint("account_id", "record_key", "deadline", "lead_days", name="uq_reminder_deliveries_once"),
        Index("ix_reminder_deliveries_email", "email_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id", ondelete="CASCADE"))
    # The application record's id as 「我的申请」 serves it: a plan id, or `catalog:<program id>`.
    record_key: Mapped[str] = mapped_column(String(80))
    deadline: Mapped[date] = mapped_column(Date)
    lead_days: Mapped[int] = mapped_column(Integer)
    email_id: Mapped[str] = mapped_column(String(36), ForeignKey("reminder_emails.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
