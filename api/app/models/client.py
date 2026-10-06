import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_client_id() -> str:
    """Anonymous subject id. Lives in a cookie until real accounts exist."""
    return str(uuid.uuid4())


class Client(Base):
    """An anonymous applicant. Upgrades to a real account later without moving the profile."""

    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="client", cascade="all, delete-orphan")


class Profile(Base):
    """The applicant's background. One row per client."""

    __tablename__ = "profiles"

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )

    current_education_level: Mapped[str | None] = mapped_column(String(32))
    school_origin: Mapped[str | None] = mapped_column(String(16))
    school_name: Mapped[str | None] = mapped_column(String(128))
    domestic_tier: Mapped[str | None] = mapped_column(String(16))
    overseas_band: Mapped[str | None] = mapped_column(String(32))
    major: Mapped[str | None] = mapped_column(String(64))
    gpa_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    gpa_scale: Mapped[float | None] = mapped_column(Numeric(5, 2))
    target_degree_level: Mapped[str | None] = mapped_column(String(32))
    target_field: Mapped[str | None] = mapped_column(String(64))
    intake: Mapped[str | None] = mapped_column(String(16))
    english_score: Mapped[str | None] = mapped_column(String(64))
    annual_budget_cny: Mapped[float | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    client: Mapped[Client] = relationship(back_populates="profile")
