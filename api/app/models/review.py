"""Review criteria and the reviews written against them.

Two ideas live here, and the difference between them is the product's whole claim:

- A **criterion** is a point someone checks a material against, together with the official page it
  was read from. `source_id` is NOT NULL in the database, not merely in a service, because a
  requirement nobody can point at is exactly the invented requirement this project refuses to
  produce; `verified_at` starts empty and only a human ever sets it.
- A **review** is one person's verdict on one exact version of one material, plus the findings that
  justify it. `criterion_id` is NOT NULL for the same reason: a conclusion that cannot name the
  requirement it failed is not a conclusion the applicant can act on.

The enumerations are constrained by CHECK constraints rather than only by the Python enums, so a
hand-written statement cannot store a value this code has never heard of. `app/services/reviews.py`
holds the rules that need more than one row to decide.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Imported rather than copied: the CHECK constraints in both modules spell their value lists the same
# way, and a second copy would be free to drift from the first.
from app.models.document import sql_in_list

SCOPE_VALUES = (
    "gs",
    "transcript",
    "cv",
    "ps",
    "recommendation",
    "language",
    "general",
)

CHECK_TYPE_VALUES = (
    "presence",
    "length",
    "language",
    "evidence",
    "consistency",
)

OVERALL_VALUES = (
    "pass",
    "needs_revision",
    "insufficient_evidence",
)

SEVERITY_VALUES = (
    "info",
    "warning",
    "blocker",
)


class CriterionScope(StrEnum):
    """Which kind of material a criterion is about, or `general` for any of them.

    The scoped values are deliberately the same strings as `DocumentKind`: that is what lets a
    finding be refused when it cites, say, a Genuine Student criterion against a transcript.
    """

    GS = "gs"
    TRANSCRIPT = "transcript"
    CV = "cv"
    PS = "ps"
    RECOMMENDATION = "recommendation"
    LANGUAGE = "language"
    GENERAL = "general"


class CheckType(StrEnum):
    PRESENCE = "presence"
    LENGTH = "length"
    LANGUAGE = "language"
    EVIDENCE = "evidence"
    CONSISTENCY = "consistency"


class CriterionStatus(StrEnum):
    """Chinese because the interface shows these two values as-is, exactly as `SourceStatus` does."""

    UNVERIFIED = "待核验"
    VERIFIED = "已核验"


class ReviewOverall(StrEnum):
    PASS = "pass"
    NEEDS_REVISION = "needs_revision"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class ReviewCriterion(Base):
    """One point a review checks a material against, and the page it came from."""

    __tablename__ = "review_criteria"
    __table_args__ = (
        CheckConstraint(f"scope IN ({sql_in_list(SCOPE_VALUES)})", name="ck_review_criteria_scope"),
        CheckConstraint(
            f"check_type IN ({sql_in_list(CHECK_TYPE_VALUES)})",
            name="ck_review_criteria_check_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    scope: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    check_type: Mapped[str] = mapped_column(String(16))

    # The machine-checkable half of the criterion, and null when there is none. An empty object would
    # claim "checkable, with no rules"; null says "this one only a human can judge", which is the
    # truth about most of these. Postgres JSONB because the parent design specifies it and the only
    # reader loads the whole object.
    rule: Mapped[dict | None] = mapped_column(JSONB)

    # RESTRICT, not CASCADE: deleting a page must not silently take the requirements read from it.
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="RESTRICT")
    )

    # No server default for `verified_at`, deliberately. A record can only claim verification when a
    # human sets the date, and a default would make every seeded criterion look checked.
    status: Mapped[str] = mapped_column(String(16), default=CriterionStatus.UNVERIFIED)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentReview(Base):
    """One human verdict on one version of one material.

    `version_id` is NOT NULL because a verdict describes exact bytes: the applicant may upload a
    revision the day after a review, and a finding that no longer names the file it was about cannot
    be checked or acted on. `reviewed_by` is NOT NULL for the same reason the spec demands it — a
    judgement nobody is willing to sign is not one to show an applicant.
    """

    __tablename__ = "document_reviews"
    __table_args__ = (
        CheckConstraint(f"overall IN ({sql_in_list(OVERALL_VALUES)})", name="ck_document_reviews_overall"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE")
    )
    version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    overall: Mapped[str] = mapped_column(String(24))
    summary: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentReviewFinding(Base):
    """One concrete thing to fix, always citing the criterion it fails."""

    __tablename__ = "document_review_findings"
    __table_args__ = (
        CheckConstraint(
            f"severity IN ({sql_in_list(SEVERITY_VALUES)})",
            name="ck_document_review_findings_severity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_reviews.id", ondelete="CASCADE")
    )
    # RESTRICT here too: the findings are the reason a criterion cannot be quietly deleted, and this
    # is the constraint the spec's "a cited criterion cannot be deleted" scenario pins.
    criterion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("review_criteria.id", ondelete="RESTRICT")
    )
    severity: Mapped[str] = mapped_column(String(16))
    finding: Mapped[str] = mapped_column(Text)
    # Null when the finding quotes nothing. An empty string would be a quote someone took and found
    # empty, which is a different and untrue claim.
    evidence_quote: Mapped[str | None] = mapped_column(Text)
