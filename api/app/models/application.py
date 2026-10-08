from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ApplicationOrigin(StrEnum):
    """Who chose this row.

    The default is `user` and there is no `system` member, because a portfolio is the applicant's
    decision rather than something computed from the profile: nothing the browser or the agent writes
    may claim a human made the choice by leaving the field out.
    """

    USER = "user"
    AGENT = "agent"


class ApplicationTier(StrEnum):
    """The reach / match / safety band. The values are Chinese because they are shown as-is."""

    REACH = "冲"
    MATCH = "稳"
    SAFETY = "保"


class ApplicationStatus(StrEnum):
    """Where the applicant is with one choice. Plain strings, like the sibling task tables."""

    CONSIDERING = "considering"
    APPLYING = "applying"
    EXCLUDED = "excluded"


class Application(Base):
    """One program in one applicant's portfolio. Its own row, so the choice can be traced and edited."""

    __tablename__ = "applications"
    __table_args__ = (
        # One row per program: two rows for the same program are the same choice written twice.
        UniqueConstraint("client_id", "program_id"),
        # At most one first choice per applicant, and the predicate is the whole constraint. The two
        # constraints are deliberately separate — this index is not a second spelling of the one above.
        # Without its `WHERE`, a unique index on `client_id` would refuse the applicant's *second*
        # program instead, and an index on `(client_id, program_id)` would merely repeat the
        # uniqueness above, so `tests/test_application_model.py` reads the definition back from
        # `pg_indexes` and refuses to let the predicate go missing quietly.
        Index(
            "uq_applications_one_primary_per_client",
            "client_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE")
    )
    program_id: Mapped[str] = mapped_column(String(64), ForeignKey("programs.id"))

    # Required rather than defaulted: a portfolio with no band is not a portfolio with an unknown one.
    # The membership is stated here and enforced where the row enters the system, in the request
    # schema `app/schemas/application.py`; the column is a plain string, like `roadmap_tasks.status`.
    tier: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default=ApplicationStatus.CONSIDERING)

    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    # Nullable on purpose, and `None` is the default: an official deadline is unknown until somebody
    # looks one up, and a date the system invented is worse than a blank. The url is the same claim.
    official_deadline: Mapped[date | None] = mapped_column(Date, default=None)
    deadline_source_url: Mapped[str | None] = mapped_column(Text, default=None)

    # Set when the system could not tier the program and the applicant added it by hand.
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    origin: Mapped[str] = mapped_column(String(8), default=ApplicationOrigin.USER)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
