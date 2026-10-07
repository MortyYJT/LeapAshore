"""Tests for the `applications` table: the applicant's reach / match / safety portfolio.

The portfolio used to live in the browser, so nothing in the database could refuse a second "first
choice" or a duplicate row for one program. Both refusals are database constraints here, and the two
are separate: `UNIQUE (client_id, program_id)` says one row per program, and a *partial* unique index
on `is_primary` says at most one first choice per applicant. An index that lost its `WHERE` clause is
not the second constraint at all, so one test below asserts on the stored index definition and another
proves the constraint refuses a second primary across two *different* programs, where the program
uniqueness cannot be the reason it refused.

The three probe programs these tests write belong to the module and are removed with it, so the shared
development database is left as it was found; the subjects are swept by `conftest`'s autouse fixture,
and the application rows follow their subject through the foreign key's CASCADE.
"""

import uuid

import pytest
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.application import Application, ApplicationOrigin
from app.models.client import Client
from app.models.program import Program, University
from app.models.source import Source
from tests.conftest import database_is_reachable

PRIMARY_INDEX = "uq_applications_one_primary_per_client"
PROGRAM_UNIQUE = "applications_client_id_program_id_key"

TEST_UNIVERSITY_ID = "test-applications-university"
TEST_SOURCE_ID = "test-applications-source"
TEST_PROGRAM_IDS = (
    "test-applications-program-reach",
    "test-applications-program-match",
    "test-applications-program-safety",
)
REACH, MATCH, SAFETY = TEST_PROGRAM_IDS


def _write_the_probe_catalogue(session) -> None:
    """Create the fixture rows that are missing, and leave any that are already there alone.

    Being create-if-missing rather than insert is what keeps this fixture from being its own trap:
    a run that fails between the insert and the teardown would otherwise leave the rows behind, and
    the next run would fail while *setting up* — on a duplicate key, for a reason that has nothing
    to do with what it tests. Measured during this task's red phase: the module fixture inserted the
    source, the tests failed because the table did not exist yet, the teardown died on that same
    missing table, and the next run then reported
    ``UniqueViolation: duplicate key value violates unique constraint "sources_pkey"``. Reading the
    rows back first makes a leaked fixture row repairable by the following run, which then removes
    it again.
    """
    if session.get(Source, TEST_SOURCE_ID) is None:
        session.add(
            Source(
                id=TEST_SOURCE_ID,
                url="https://example.edu/test-applications",
                title="测试来源",
                publisher=TEST_UNIVERSITY_ID,
            )
        )
        session.flush()
    if session.get(University, TEST_UNIVERSITY_ID) is None:
        session.add(University(id=TEST_UNIVERSITY_ID, name="测试大学"))
        session.flush()
    for program_id in TEST_PROGRAM_IDS:
        if session.get(Program, program_id) is None:
            session.add(
                Program(
                    id=program_id,
                    university_id=TEST_UNIVERSITY_ID,
                    name=f"测试项目 {program_id}",
                    source_id=TEST_SOURCE_ID,
                )
            )
    session.flush()


def _remove_the_probe_catalogue(session) -> None:
    """Take the probe rows away again, in the order the foreign keys demand.

    Applications go before the programs they name. The table is asked about first because this
    teardown also runs when the migration has not been applied yet — the red phase of this very
    task — and a delete against a table that does not exist aborts the whole teardown, leaving the
    fixture rows behind for the next run to trip over. The rows come back in the same state either
    way: nothing was written to a table that was not there.
    """
    if inspect(session.get_bind()).has_table(Application.__tablename__):
        session.execute(delete(Application).where(Application.program_id.in_(TEST_PROGRAM_IDS)))
    session.execute(delete(Program).where(Program.id.in_(TEST_PROGRAM_IDS)))
    session.execute(delete(Source).where(Source.id == TEST_SOURCE_ID))
    session.execute(delete(University).where(University.id == TEST_UNIVERSITY_ID))
    session.flush()


@pytest.fixture(autouse=True, scope="module")
def the_probe_programs_these_tests_choose_between():
    """Write the three programs every test here picks from, and take them away afterwards.

    `programs.source_id` is NOT NULL, so a probe program needs its own source and institution.
    The programs are removed at the end rather than left in place as stable fixture rows, because
    `test_seed.py` dumps *every* stored program into the mirror guard, and a stray probe row would
    be reported as a catalogue that no longer matches `web/lib/programs.ts`.

    A guard for an unreachable database is deliberate: the tests themselves skip through
    `require_db`, and a teardown that reached for a container that is down would turn a skipped
    suite into an error, which is the failure `conftest` documents at length.
    """
    reachable = database_is_reachable()
    if reachable:
        with SessionLocal() as session:
            _write_the_probe_catalogue(session)
            session.commit()

    yield

    if not reachable or not database_is_reachable():
        return
    with SessionLocal() as session:
        _remove_the_probe_catalogue(session)
        session.commit()


def _subject(db_session) -> str:
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.flush()
    return client_id


def _application(client_id: str, program_id: str, **overrides) -> Application:
    values = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "program_id": program_id,
        "tier": "稳",
    }
    values.update(overrides)
    return Application(**values)


def test_a_new_choice_is_the_applicants_own_and_has_no_invented_deadline(db_session, require_db):
    """The defaults are the rule this table exists for, plus one honest blank.

    A portfolio row is the applicant's decision, so `origin` has to default to `user`: a row the
    browser or the agent wrote must not be able to claim a human chose it by leaving the field out.
    An official deadline nobody has looked up is unknown, and unknown is `NULL` rather than a date
    the system made up.
    """
    client_id = _subject(db_session)
    db_session.add(_application(client_id, REACH))
    db_session.commit()

    row = db_session.execute(
        select(Application).where(Application.client_id == client_id)
    ).scalar_one()
    assert row.origin == ApplicationOrigin.USER
    assert row.origin == "user"
    assert row.is_primary is False
    assert row.needs_review is False
    assert row.official_deadline is None, "a deadline nobody looked up must not be invented"
    assert row.deadline_source_url is None
    assert row.created_at is not None
    assert row.updated_at is not None


def test_one_row_per_applicant_and_program(db_session, require_db):
    """`UNIQUE (client_id, program_id)`: the same program cannot sit in one portfolio twice.

    The refusal has to name the constraint it came from. An `IntegrityError` on its own would be
    satisfied by the partial index below refusing this row for a completely different reason.
    """
    client_id = _subject(db_session)
    db_session.add(_application(client_id, MATCH))
    db_session.commit()

    db_session.add(_application(client_id, MATCH))
    with pytest.raises(IntegrityError) as refused:
        db_session.commit()
    db_session.rollback()

    assert PROGRAM_UNIQUE in str(refused.value), str(refused.value)
    assert "client_id, program_id" in str(refused.value), str(refused.value)


def test_a_second_primary_is_refused_across_two_different_programs(db_session, require_db):
    """The partial unique index, and the proof that it is not the program uniqueness in disguise.

    The two rows name two *different* programs, so `UNIQUE (client_id, program_id)` cannot be what
    refuses the second one, and the error has to name the partial index for the same reason. A test
    that reused one program, or accepted any `IntegrityError`, would pass with no primary constraint
    at all.
    """
    client_id = _subject(db_session)
    db_session.add(_application(client_id, REACH, is_primary=True))
    db_session.commit()

    db_session.add(_application(client_id, MATCH, is_primary=True))
    with pytest.raises(IntegrityError) as refused:
        db_session.commit()
    db_session.rollback()

    assert PRIMARY_INDEX in str(refused.value), str(refused.value)

    # The refused row is gone, and the first primary is untouched.
    rows = db_session.execute(
        select(Application).where(Application.client_id == client_id)
    ).scalars().all()
    assert [(row.program_id, row.is_primary) for row in rows] == [(REACH, True)]


def test_several_choices_that_are_not_primary_are_allowed(db_session, require_db):
    """A second row for the same applicant is the ordinary case, and the index must not forbid it.

    This is the shape a missing `WHERE` takes: a unique index on `client_id` with its predicate
    dropped refuses the second *program*, and one on `(client_id, program_id)` merely repeats the
    uniqueness constraint. Either way it is not the constraint the design asks for, and this fails.
    """
    client_id = _subject(db_session)
    for program_id in (REACH, MATCH, SAFETY):
        db_session.add(_application(client_id, program_id))
    db_session.commit()

    kept = db_session.execute(
        select(Application.program_id).where(Application.client_id == client_id)
    ).scalars().all()
    assert set(kept) == set(TEST_PROGRAM_IDS)


def test_two_applicants_may_each_have_their_own_primary(db_session, require_db):
    """The constraint counts primaries per applicant, not across the whole table."""
    first = _subject(db_session)
    second = _subject(db_session)
    db_session.add(_application(first, REACH, is_primary=True))
    db_session.add(_application(second, MATCH, is_primary=True))
    db_session.commit()

    primaries = db_session.execute(
        select(Application.client_id).where(Application.is_primary.is_(True))
    ).scalars().all()
    assert {first, second} <= set(primaries)


def test_the_stored_primary_index_still_carries_its_predicate(db_session, require_db):
    """The index in the database is only the constraint when its `WHERE` clause survived.

    Autogenerate does not always emit `postgresql_where`, and an index that lost it is a different
    constraint that a behavioural test can still pass for the wrong reason. The predicate is
    therefore read back from `pg_indexes` rather than trusted to the migration source.
    """
    definitions = dict(
        db_session.execute(
            text(
                "select indexname, indexdef from pg_indexes "
                "where tablename = 'applications' and indexname = :name"
            ),
            {"name": PRIMARY_INDEX},
        ).all()
    )
    assert PRIMARY_INDEX in definitions, "the partial unique index is missing from the database"
    definition = definitions[PRIMARY_INDEX].lower()
    # The whole shape, not just the word `where`: unique, on the applicant, and partial on the flag.
    assert definition.startswith("create unique index"), definition
    assert definition.endswith("(client_id) where is_primary"), definition

    # The two constraints are separate rows in the catalogue, not one standing in for the other.
    constraints = dict(
        db_session.execute(
            text(
                "select conname, pg_get_constraintdef(oid) from pg_constraint "
                "where conrelid = 'applications'::regclass and contype = 'u'"
            )
        ).all()
    )
    assert PROGRAM_UNIQUE in constraints, constraints
    assert constraints[PROGRAM_UNIQUE] == "UNIQUE (client_id, program_id)", constraints


def test_deleting_an_applicant_removes_the_whole_portfolio(db_session, require_db):
    """Deleting a subject has to take its choices with it, or the table fills with orphan rows.

    The rows are read back through a *second* session on purpose. `db_session` wrote them and holds
    them in its identity map, so asking it again would answer from memory: measured, the first
    version of this test passed the rows back unchanged even after the delete, which is the failure
    mode `expire_on_commit=False` leaves in place. A fresh session has no such memory and issues a
    real select.
    """
    client_id = _subject(db_session)
    application_ids = []
    for program_id in (REACH, MATCH):
        application = _application(client_id, program_id)
        application_ids.append(application.id)
        db_session.add(application)
    db_session.commit()

    db_session.delete(db_session.get(Client, client_id))
    db_session.commit()

    with SessionLocal() as fresh:
        for application_id in application_ids:
            assert fresh.get(Application, application_id) is None, "the row outlived its applicant"
