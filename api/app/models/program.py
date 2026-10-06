from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class University(Base):
    """An institution a program belongs to."""

    __tablename__ = "universities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(String(32), default="澳大利亚")
    official_url: Mapped[str | None] = mapped_column(Text)

    programs: Mapped[list["Program"]] = relationship(back_populates="university")


class Program(Base):
    """One admission program. Every value still awaits review against its source."""

    __tablename__ = "programs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    university_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("universities.id", ondelete="CASCADE")
    )

    name: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    degree_level: Mapped[str | None] = mapped_column(String(32))
    field: Mapped[str | None] = mapped_column(String(64))
    duration: Mapped[str | None] = mapped_column(String(32))

    # Thresholds are nullable: an institution that publishes no non-211 baseline has an unknown
    # value, not a zero one. `Numeric` reads back as `Decimal`, so that is the annotation; the
    # schemas serialise a JSON number, which is where `float` belongs.
    minimum_mark: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    non_211_minimum_mark: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    requires_cognate: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_supervisor: Mapped[bool] = mapped_column(Boolean, default=False)
    research_proposal_required: Mapped[bool] = mapped_column(Boolean, default=False)
    english_requirement: Mapped[str | None] = mapped_column(Text)

    # Mandatory, like `review_criteria.source_id` and `document_review_findings.criterion_id`: a
    # program is a claim about an official page, so a program with no page is not a program with an
    # unknown source. The router still checks the row it reads, because a check that only holds in
    # the schema is worth keeping visible at the point of use.
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"))
    data_status: Mapped[str] = mapped_column(String(16), default="待核验")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    university: Mapped[University] = relationship(back_populates="programs")
    prerequisites: Mapped[list["ProgramPrerequisite"]] = relationship(
        back_populates="program", cascade="all, delete-orphan"
    )


class ProgramPrerequisite(Base):
    """A prerequisite line of a program, kept as short display text."""

    __tablename__ = "program_prerequisites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    program_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("programs.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    program: Mapped[Program] = relationship(back_populates="prerequisites")
