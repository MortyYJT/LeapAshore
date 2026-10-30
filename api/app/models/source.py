from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text
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
    # verification when a human sets the date explicitly: the only writer is an admin's confirmation
    # (`app.services.source_verification`), and a trigger refuses any other non-null value (alembic
    # c8e1f4a7b2d9, openspec source-verification D4).
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


class SourceVerification(Base):
    """One admin's confirmation of a page at one snapshot, or its withdrawal (openspec source-verification D3).

    Append-only. The trigger on `sources` accepts a new `verified_at` only when a `verify` row with the
    same source and moment, written in the same transaction (`txid`), names an admin account.
    `decided_at` is deliberately not called `verified_at`: that name means one thing in this schema.
    """

    __tablename__ = "source_verifications"
    __table_args__ = (
        CheckConstraint("action IN ('verify', 'revoke')", name="ck_source_verifications_action"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(16))
    # The version the person read; a confirmation describes those bytes, not the page in general.
    content_sha256: Mapped[str] = mapped_column(String(64))
    # SET NULL: deleting the admin's account removes who, not the fact that the page was checked.
    account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    txid: Mapped[int] = mapped_column(BigInteger, server_default=text("txid_current()"))
