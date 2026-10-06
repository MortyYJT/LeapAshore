from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class RoadmapPhase(Base):
    """One stage of the application timeline. Configuration, not applicant data."""

    __tablename__ = "roadmap_phases"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    subtitle: Mapped[str | None] = mapped_column(Text)
    # Days before the intake date. The interface derives every suggested date from this.
    offset_days: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    materials: Mapped[list["MaterialTemplate"]] = relationship(back_populates="phase_ref")


class MaterialTemplate(Base):
    """One thing to prepare. The applicant's copy of it lives in roadmap_tasks."""

    __tablename__ = "material_templates"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # RESTRICT rather than CASCADE: deleting a phase while materials still point at it would silently
    # drop requirements the applicant is working through.
    phase: Mapped[str] = mapped_column(
        String(32), ForeignKey("roadmap_phases.key", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    applies_to: Mapped[str] = mapped_column(String(16), default="all")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Nullable: most materials have no official page yet, and a manufactured one is worse than none.
    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sources.id"))

    phase_ref: Mapped[RoadmapPhase] = relationship(back_populates="materials")
