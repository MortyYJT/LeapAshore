"""Applicant-owned manual applications and preparation overlays for catalogue selections."""

from datetime import date, datetime
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models.versioning import Versioned


class ApplicationPlan(Versioned, Base):
    __tablename__ = "application_plans"
    __table_args__ = (
        UniqueConstraint("client_id", "catalog_program_id"),
        # One row per create request: a retried `POST` carries the same key and finds this row.
        UniqueConstraint("client_id", "create_key", name="uq_application_plans_create_key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    catalog_program_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("programs.id"), nullable=True
    )
    school: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(String(300), default="")
    round: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="considering")
    deadline_override: Mapped[bool] = mapped_column(Boolean, default=False)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    materials_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    material_notes: Mapped[str] = mapped_column(Text, default="")
    # The `Idempotency-Key` of the request that created a manual record; null for overlays.
    create_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
