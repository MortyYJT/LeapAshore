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
from sqlalchemy.dialects.postgresql import JSONB
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
    # The single flag the per-material ticks replaced (PRD 3.7). No longer read or written; kept so an
    # image from before the change still runs against this table.
    materials_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    material_notes: Mapped[str] = mapped_column(Text, default="")
    # The applicant's ticks on the catalogue's materials for this program: material key -> the digest
    # of the requirement as it read when it was ticked (`app.collect.materials.digest`). A tick whose
    # digest is not the stored requirement's was given for an earlier wording and does not count.
    material_ticks: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # The applicant's own checklist lines: `[{"id", "label", "done"}]`, in their order.
    custom_materials: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # The `Idempotency-Key` of the request that created a manual record; null for overlays.
    create_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
