"""Tests for the placeholder catalogue seed.

The fixtures run against the shared development database, so every test here clears the rows it
cares about first. Without that, `test_seed_is_idempotent` would silently depend on whether a
developer had already run `make seed`, and it would pass for the wrong reason.
"""

from sqlalchemy import delete, func, select

from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source, SourceStatus, SourceVersion
from app.seed import PROGRAMS, UNIVERSITIES, seed_programs

PROGRAM_IDS = [row["id"] for row in PROGRAMS]
UNIVERSITY_IDS = [row["id"] for row in UNIVERSITIES]


def clear_catalogue(session) -> None:
    """Remove the seeded catalogue so a test starts from a known state."""
    source_ids = select(Source.id).where(Source.publisher.in_(UNIVERSITY_IDS)).scalar_subquery()
    session.execute(delete(SourceVersion).where(SourceVersion.source_id.in_(source_ids)))
    # Programs reference their source, so they have to go before it.
    session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id.in_(PROGRAM_IDS)))
    session.execute(delete(Program).where(Program.id.in_(PROGRAM_IDS)))
    session.execute(delete(Source).where(Source.id.in_(source_ids)))
    session.execute(delete(University).where(University.id.in_(UNIVERSITY_IDS)))
    session.commit()


def test_seed_is_idempotent(db_session, require_db):
    clear_catalogue(db_session)
    first = seed_programs(db_session)
    second = seed_programs(db_session)
    assert first == len(PROGRAMS)
    assert second == 0, "re-running the seed must not duplicate rows"


def test_seed_does_not_duplicate_sources_or_prerequisites(db_session, require_db):
    """Idempotency has to hold for the child rows too, not just the program count."""
    clear_catalogue(db_session)
    expected = sum(len(row["prerequisites"]) for row in PROGRAMS)
    seed_programs(db_session)
    seed_programs(db_session)

    programs = db_session.execute(select(func.count()).select_from(Program)).scalar()
    prerequisites = db_session.execute(select(func.count()).select_from(ProgramPrerequisite)).scalar()

    assert programs == len(PROGRAMS)
    assert prerequisites == expected


def test_seeded_programs_are_not_marked_verified(db_session, require_db):
    """Every seeded program is placeholder data and must say so."""
    seed_programs(db_session)
    statuses = db_session.execute(select(func.distinct(Program.data_status))).scalars().all()
    assert statuses == ["待核验"]


def test_seeded_sources_have_no_verification_date(db_session, require_db):
    seed_programs(db_session)
    rows = db_session.execute(
        select(Source).where(Source.publisher.in_(UNIVERSITY_IDS))
    ).scalars().all()
    assert rows, "the seed must create sources"
    assert len(rows) == len(PROGRAMS), "one source per program"
    assert all(row.verified_at is None for row in rows)
    assert all(row.status == SourceStatus.UNVERIFIED for row in rows)


def test_every_program_points_at_a_source(db_session, require_db):
    seed_programs(db_session)
    orphans = db_session.execute(
        select(Program.id).where(Program.source_id.is_(None))
    ).scalars().all()
    assert orphans == [], f"programs without a source: {orphans}"


def test_expected_universities_are_present(db_session, require_db):
    seed_programs(db_session)
    names = set(db_session.execute(select(University.name)).scalars().all())
    # The plan wrote 莫纳什大学 here; web/lib/programs.ts, which this seed must mirror exactly,
    # has always spelled Monash 蒙纳士大学. The frontend value wins.
    assert {"新南威尔士大学", "悉尼大学", "蒙纳士大学"} <= names
