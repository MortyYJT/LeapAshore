from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SourceStatus(StrEnum):
    """Values are Chinese because they are shown in the interface as-is."""

    UNVERIFIED = "待核验"
    VERIFIED = "已核验"
    DEAD = "失效"


class SourceVersionStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class Source(Base):
    """One official page that a claim can be traced back to."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)

    # Defaults to unverified and has no server-side default for verified_at. A record can only claim
    # verification when a human sets the date explicitly.
    status: Mapped[str] = mapped_column(String(16), default=SourceStatus.UNVERIFIED)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["SourceVersion"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class SourceVersion(Base):
    """A fetched snapshot of a source. Approval is manual, so status starts pending."""

    __tablename__ = "source_versions"
    __table_args__ = (UniqueConstraint("source_id", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="CASCADE")
    )
    version_no: Mapped[int] = mapped_column(Integer)

    requested_url: Mapped[str | None] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_type: Mapped[str | None] = mapped_column(String(128))
    content_bytes: Mapped[int | None] = mapped_column(Integer)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    body_text: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(24), default=SourceVersionStatus.PENDING_REVIEW)
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source: Mapped[Source] = relationship(back_populates="versions")
