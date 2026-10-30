"""Knowledge gaps: what the advisor could not answer, for a person to review (openspec knowledge-gaps).

A gap is one distinct thing the catalogue lacks (a school, a subject at a school, a topic on its pages),
keyed by the gate's own signals (D2) and holding no personal data. A report is one refusal that added to
it: the question, cut to 500 characters, and its asker only as a keyed hash (D4). Reports are deleted with
their subject and after 90 days; gaps are kept (D5).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # sha256 of the key parts (`services.knowledge_gaps.gap_key`); concurrent refusals upsert on it.
    gap_key: Mapped[str] = mapped_column(String(64), unique=True)
    route: Mapped[str] = mapped_column(String(16))  # requirements | passages
    reason: Mapped[str] = mapped_column(String(32))  # the gate's refusal reason, or school_missing / nothing_checkable
    university_ids: Mapped[list] = mapped_column(JSONB, default=list)
    fields: Mapped[list] = mapped_column(JSONB, default=list)  # Program.field areas
    subject_words: Mapped[list] = mapped_column(JSONB, default=list)
    topics: Mapped[list] = mapped_column(JSONB, default=list)  # page topics (tuition, ...)
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"))
    review_note: Mapped[str | None] = mapped_column(Text)
    # What a `recollect` review sent to the collection queue, per school.
    recollect: Mapped[dict | None] = mapped_column(JSONB)


class KnowledgeGapReport(Base):
    __tablename__ = "knowledge_gap_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gap_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_gaps.id", ondelete="CASCADE"), index=True)
    # HMAC-SHA256 of the subject id under KNOWLEDGE_GAP_HASH_KEY; NULL when no key is configured.
    reporter_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    question: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
