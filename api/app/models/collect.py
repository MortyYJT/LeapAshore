"""The collection queue's durable state (openspec/changes/archive/2026-10-30-collect-queue, D1 and D7).

Celery only runs the queue; what has been fetched, what it said and what changed lives here, so a lost
broker message or a dead worker loses nothing. Nothing here is shown to applicants and nothing here is
a verification: the catalogue is still written only by the importer, from committed requirement files.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PageState(StrEnum):
    PENDING = "pending"          # known, not yet sent to the broker
    QUEUED = "queued"            # sent; a worker will pick it up
    DONE = "done"                # fetched and extracted; `result` holds the program
    UNCHANGED = "unchanged"      # fetched; same HTML or visible text as last time, no model call
    BLOCKED = "blocked"          # robots.txt, a recorded refusal, or HTTP 401/403/429: never retried around
    FAILED = "failed"            # gone (404) or still failing after the retries
    DEFERRED = "deferred"        # not attempted: budget reached, or it needs a renderer this host lacks
    NEEDS_HUMAN = "needs_human"  # the model's answer was unusable, or the page lost every value


class CollectPage(Base):
    """One official page the queue collects, with the last thing it learned from it."""

    __tablename__ = "collect_pages"
    __table_args__ = (UniqueConstraint("school_key", "url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    school_key: Mapped[str] = mapped_column(String(96), index=True)
    url: Mapped[str] = mapped_column(Text)
    program_name: Mapped[str] = mapped_column(Text)
    cricos_code: Mapped[str | None] = mapped_column(String(16))
    render: Mapped[bool] = mapped_column(Boolean, default=False)
    # `file`: a program a committed requirement file already lists; `discovered`: picked from a listing.
    origin: Mapped[str] = mapped_column(String(16), default="discovered")

    state: Mapped[str] = mapped_column(String(16), default=PageState.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    # The snapshot is named by these hashes only; its path on disk is never stored (D9).
    snapshot_sha256: Mapped[str | None] = mapped_column(String(64))
    text_sha256: Mapped[str | None] = mapped_column(String(64))
    # The program in requirement-file shape after `verify` (fields with `check`, `status`).
    result: Mapped[dict | None] = mapped_column(JSONB)
    rejected: Mapped[list | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(64))
    cost_cny: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))

    # The last attempt to fetch, whatever came of it (the beat re-collects from this, D12).
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RequirementChange(Base):
    """One requirement of one page that differs from what the page said before (D7)."""

    __tablename__ = "requirement_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    page_id: Mapped[str] = mapped_column(String(36), ForeignKey("collect_pages.id", ondelete="CASCADE"), index=True)
    school_key: Mapped[str] = mapped_column(String(96), index=True)
    url: Mapped[str] = mapped_column(Text)
    program_name: Mapped[str] = mapped_column(Text)
    field: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # added | removed | changed
    old_value: Mapped[dict | list | None] = mapped_column(JSONB)
    new_value: Mapped[dict | list | None] = mapped_column(JSONB)
    old_sha256: Mapped[str | None] = mapped_column(String(64))
    new_sha256: Mapped[str | None] = mapped_column(String(64))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
