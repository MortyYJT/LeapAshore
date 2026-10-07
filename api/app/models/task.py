from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db import Base


class TaskOrigin(StrEnum):
    """Who owns a row. A recompute may only ever replace the SYSTEM rows."""

    SYSTEM = "system"
    USER = "user"
    AGENT = "agent"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class ScheduleOrigin(StrEnum):
    SUGGESTED = "suggested"
    OFFICIAL = "official"
    USER = "user"


class RoadmapTask(Base):
    """One thing the applicant has to prepare. Derived from the profile, then owned by whoever edits it."""

    __tablename__ = "roadmap_tasks"
    __table_args__ = (
        # The empty string, not NULL, marks a material that is not tied to one program: a unique
        # constraint does not constrain NULLs, so NULL would let duplicates through.
        UniqueConstraint("client_id", "material_key", "program_id"),
        Index("ix_roadmap_tasks_client_phase", "client_id", "phase"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE")
    )
    material_key: Mapped[str] = mapped_column(String(64), ForeignKey("material_templates.key"))
    program_id: Mapped[str] = mapped_column(String(64), default="")
    phase: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.PENDING)
    suggested_at: Mapped[date | None] = mapped_column(Date)
    due_at: Mapped[date | None] = mapped_column(Date)
    schedule_origin: Mapped[str] = mapped_column(String(16), default=ScheduleOrigin.SUGGESTED)

    # The rule this whole batch exists for. Defaults to system so a client-written row cannot claim to
    # be a human's decision by omitting the field.
    origin: Mapped[str] = mapped_column(String(8), default=TaskOrigin.SYSTEM)

    document_id: Mapped[str | None] = mapped_column(String(36))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TaskEvent(Base):
    """History of every change to a task or an application, whoever made it."""

    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE")
    )
    # Deliberately not a foreign key: the history must outlive the row it describes.
    task_id: Mapped[str | None] = mapped_column(String(36))
    application_id: Mapped[str | None] = mapped_column(String(36))

    actor: Mapped[str] = mapped_column(String(8))
    event: Mapped[str] = mapped_column(String(24))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    message_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
