from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, exists, func, or_
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
    # Indexed because the advisor filters programs by school in SQL (alembic 5c1e7f0a2b3d).
    university_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("universities.id", ondelete="CASCADE"), index=True
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
    # The collector's summary of the academic entry requirement, written only when its quote passed
    # `verify`; NULL is "not collected", never "none required" (alembic b7d4e2a91c60).
    academic_requirement: Mapped[str | None] = mapped_column(Text)
    # The page the academic requirement's quote is on: a shared admissions page or the program page.
    academic_source_url: Mapped[str | None] = mapped_column(Text)

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
    deadlines: Mapped[list["ProgramDeadline"]] = relationship(
        back_populates="program", cascade="all, delete-orphan", order_by="ProgramDeadline.sort_order"
    )


class ProgramPrerequisite(Base):
    """A prerequisite line of a program, kept as short display text."""

    __tablename__ = "program_prerequisites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    program_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("programs.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    program: Mapped[Program] = relationship(back_populates="prerequisites")


class ProgramDeadline(Base):
    """One application deadline a program's official page states, as collected and checked.

    The catalogue's fact about the program, shared by every applicant. It is never copied into an
    applicant's own rows (`applications.official_deadline`), so an import cannot overwrite a date
    somebody entered. Whether a deadline has passed is decided against today when it is shown, never
    stored, so it cannot go stale (openspec requirement-dates D2, D4).
    """

    __tablename__ = "program_deadlines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    program_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("programs.id", ondelete="CASCADE"), index=True
    )
    # The collector's name for the round or intake ("Round 2", "Fall 2027"); NULL when it gave none.
    label: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[date] = mapped_column(Date)
    # The verified quote the date was read from, and the page it is on.
    quote: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    program: Mapped[Program] = relationship(back_populates="deadlines")


def has_requirement_data():
    """SQL: the program states at least one requirement its page shows.

    The one rule behind every "has a requirement" count: the catalogue's filter and order, the school
    library's per-school count and the advisor's evidence gate. A requirement is an English line, a
    mark for 985/211 or for other universities, a prerequisite, an academic requirement or an
    application deadline, the rows the program page lists under 录取要求. `statesARequirement` in
    `web/lib/catalog.ts` is the same rule for the frontend; change both together. Values a collection
    file states only in words (an English note with no score, a Chinese-applicant note with no mark)
    are not stored, so they do not count.
    """
    return or_(
        Program.english_requirement.is_not(None),
        Program.minimum_mark.is_not(None),
        Program.non_211_minimum_mark.is_not(None),
        Program.academic_requirement.is_not(None),
        exists().where(ProgramPrerequisite.program_id == Program.id),
        exists().where(ProgramDeadline.program_id == Program.id),
    )
