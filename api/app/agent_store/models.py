from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AgentBase(DeclarativeBase):
    pass


class ProjectionReceipt(AgentBase):
    __tablename__ = "projection_receipts"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    projection_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdvisorThreadProjection(AgentBase):
    __tablename__ = "advisor_thread_projection"
    aggregate_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AdvisorAudit(AgentBase):
    __tablename__ = "advisor_audit"
    request_ref: Mapped[str] = mapped_column(String(128), primary_key=True)
    workflow_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_class: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class ReviewCandidate(AgentBase):
    __tablename__ = "review_candidate"
    candidate_ref: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
