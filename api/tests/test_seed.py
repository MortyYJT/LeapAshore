"""Tests for the placeholder catalogue seed.

The fixtures run against the shared development database. The tests that assert on how many rows a
run adds — and the last one, which compares stored values against the frontend source — clear the
catalogue first, so they cannot be answered by whatever a developer happened to leave in the
database. The rest seed on top of the existing rows and assert only on the seeded rows, which the
seed's own idempotency makes safe.

The last test hands the seeded rows to scripts/verify-programs-mirror.cjs, the guard that keeps the
seed and web/lib/programs.ts from drifting apart.

Clearing the catalogue also displaces the portfolio rows that name a seeded program, because
``applications.program_id`` is RESTRICT: a developer with a portfolio in a browser used to be able to
fail three of these tests with a foreign-key message that named no cause. The rows go to an autouse
fixture that puts them back once the test that swept has restored the catalogue, the same way
``conftest.clear_the_roadmap_definition`` handles ``roadmap_tasks``. A test that calls
``clear_catalogue`` has to hand its return value to ``applications_displaced_mid_run``, or the rows it
removed are lost.
"""

import json
import subprocess
import warnings
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from app.models.application import Application
from app.models.client import Client
from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source, SourceStatus, SourceVersion
from app.seed import PROGRAMS, UNIVERSITIES, seed_programs

PROGRAM_IDS = [row["id"] for row in PROGRAMS]
UNIVERSITY_IDS = [row["id"] for row in UNIVERSITIES]

# The column names a displaced portfolio row is snapshotted by, taken from the table rather than
# written out, so a column added later is carried by the restore without anyone remembering to add it
# here. The same reading `conftest.TASK_COLUMNS` takes of `roadmap_tasks`.
APPLICATION_COLUMNS = tuple(column.key for column in Application.__table__.columns)

# Rows a catalogue sweep had to remove, held until the test that swept has re-seeded the catalogue and
# the fixture below can put them back. Module scope because the list has to outlive the test that
# filled it — `conftest.task_rows_displaced_mid_run` is the session-scoped version of the same idea.
applications_displaced_mid_run: list[dict] = []

# tests/ -> api/ -> the repository root, where the guard and the frontend data live.
REPO_ROOT = Path(__file__).resolve().parents[2]
MIRROR_GUARD = REPO_ROOT / "scripts" / "verify-programs-mirror.cjs"


def json_number(value):
    """Numeric columns come back as Decimal; JSON wants a number, and null must stay null."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def clear_catalogue(session) -> list[dict]:
    """Remove the seeded catalogue, displacing any portfolio row that names a seeded program.

    ``applications.program_id`` is RESTRICT, so ``DELETE FROM programs`` is refused while one stored
    portfolio row names one of the six seeded ids, and the whole run aborts with
    ``applications_program_id_fkey`` — a message that names the constraint and not the person whose
    browser wrote the row. Measured: two rows written through the live route for the dev UI's own
    subject, then ``pytest tests/test_seed.py`` -> 3 failed with
    ``Key (id)=(usyd-master-cs) is still referenced``. Nothing about the catalogue seed is wrong in
    that run; a person clicking in the development UI simply held a portfolio.

    The rows are therefore removed here, before the programs, and returned as plain column values so
    the caller can put them back once ``seed_programs`` has restored the rows they name. They are the
    developer's rows, so a run that discarded them would break the same "leave the shared database as
    it was found" rule the subject sweep follows. ``conftest.clear_the_roadmap_definition`` is the
    same displacement one table over, for the same reason: ``roadmap_tasks.material_key`` is RESTRICT
    too. This is the catalogue's half of it.

    Order matters beyond the foreign key: the prerequisites go before the programs, and the programs
    before the sources and the universities.
    """
    stored = list(session.scalars(select(Application)))
    displaced = [{name: getattr(row, name) for name in APPLICATION_COLUMNS} for row in stored]
    for row in stored:
        session.delete(row)
    session.flush()

    source_ids = select(Source.id).where(Source.publisher.in_(UNIVERSITY_IDS)).scalar_subquery()
    session.execute(delete(SourceVersion).where(SourceVersion.source_id.in_(source_ids)))
    # Programs reference their source, so they have to go before it.
    session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id.in_(PROGRAM_IDS)))
    session.execute(delete(Program).where(Program.id.in_(PROGRAM_IDS)))
    session.execute(delete(Source).where(Source.id.in_(source_ids)))
    session.execute(delete(University).where(University.id.in_(UNIVERSITY_IDS)))
    session.commit()
    return displaced


def restore_applications(session, displaced: list[dict]) -> dict:
    """Put back the portfolio rows the catalogue sweep had to remove, as it found them.

    Called only after ``seed_programs`` has restored the catalogue, because a portfolio row names a
    program that has to exist. Three kinds of row are skipped, and only one of them is news:

    - the subject is gone, because it was one a test created and the autouse subject sweep deleted. A
      portfolio row for a subject the run removed is expected to be unrestorable, and its absence is
      not.
    - the program is gone, because the catalogue the seed writes no longer carries it. The row cannot
      be re-inserted while the foreign key says so, and the honest answer is to name the row rather
      than fail the run on a fact the run did not change.
    - the row is already back, or the subject already holds that program, or the subject already has a
      first choice. Left alone, so the restore cannot collide with itself and cannot break
      ``UNIQUE (client_id, program_id)`` or the partial index ``uq_applications_one_primary_per_client``
      — a test that wrote a new portfolio for a pre-existing subject leaves that subject holding rows
      of its own, and re-inserting the displaced ones under them would turn a green run red.

    Returns the counts, so a caller can report what became of the rows it was given without reading the
    database again.
    """
    known_programs = set(session.scalars(select(Program.id)))
    already_held = set(
        session.execute(select(Application.client_id, Application.program_id)).all()
    )
    held_primaries = set(
        session.scalars(select(Application.client_id).where(Application.is_primary))
    )
    restored = skipped_without_a_subject = skipped_without_a_program = skipped_as_a_duplicate = 0
    for values in displaced:
        if session.get(Client, values["client_id"]) is None:
            skipped_without_a_subject += 1
            continue
        if values["program_id"] not in known_programs:
            warnings.warn(
                f"portfolio row {values['id']} for client {values['client_id']} names program "
                f"{values['program_id']!r}, which the catalogue seed no longer writes, so the row "
                "cannot be restored and is dropped. To keep it, the program has to come back to "
                "web/lib/programs.ts and api/app/seed.py; otherwise the stale row can be deleted.",
                stacklevel=2,
            )
            skipped_without_a_program += 1
            continue
        if (
            session.get(Application, values["id"]) is not None
            or (values["client_id"], values["program_id"]) in already_held
            or (values["is_primary"] and values["client_id"] in held_primaries)
        ):
            skipped_as_a_duplicate += 1
            continue
        session.add(Application(**values))
        already_held.add((values["client_id"], values["program_id"]))
        if values["is_primary"]:
            held_primaries.add(values["client_id"])
        restored += 1
    return {
        "restored": restored,
        "skipped_without_a_subject": skipped_without_a_subject,
        "skipped_without_a_program": skipped_without_a_program,
        "skipped_as_a_duplicate": skipped_as_a_duplicate,
    }


@pytest.fixture(autouse=True)
def restore_the_rows_the_catalogue_sweep_displaced(db_session):
    """Restore, after each test in this module, the portfolio rows ``clear_catalogue`` removed.

    A fixture rather than a line in each test, because the sweep is called by three of them and a
    fourth added later must not be the one that forgets. It requests ``db_session`` so it tears down
    before that fixture closes the session, and it runs while the catalogue the test seeded is still
    there, which is what a portfolio row needs to be re-inserted. It is autouse, so no test declares
    it: the three that sweep have nothing to add to the call, and one that forgot would leave the
    database short of rows it did not write.

    The displaced rows are accumulated in ``applications_displaced_mid_run``, which is module scope
    for the same reason ``conftest.task_rows_displaced_mid_run`` is session scope: the list has to
    outlive the test that filled it. Handing a fresh list to each test and expecting the test to put
    its rows in it does not work — the test's own local name shadows it, so ``clear_catalogue``'s
    return value was dropped and the rows were lost with nothing red. Measured with one planted row:
    the suite stayed green, and the row was gone afterwards.

    A test that writes a portfolio for a subject the database already held leaves that subject with
    rows of its own, so the restore skips what would collide rather than forcing the developer's row
    back on top of it. See ``restore_applications``.
    """
    yield
    displaced, applications_displaced_mid_run[:] = applications_displaced_mid_run[:], []
    if not session_is_usable(db_session):
        return
    restored = restore_applications(db_session, displaced)
    db_session.commit()
    if restored["skipped_without_a_program"]:
        warnings.warn(
            f"{restored['skipped_without_a_program']} portfolio row(s) could not be restored because "
            "the catalogue seed no longer writes the program they name; they were dropped.",
            stacklevel=2,
        )


def session_is_usable(session) -> bool:
    """True when the session can still reach the database, so a teardown can decide whether to run.

    The same rule ``conftest.database_is_reachable`` follows: a container that went away mid-run means
    "there is nothing to restore", not a teardown error on top of whatever the run already reported.
    """
    try:
        session.execute(select(1))
    except Exception:  # noqa: BLE001 - any failure means the session cannot be used
        return False
    return True


def test_seed_is_idempotent(db_session, require_db):
    applications_displaced_mid_run.extend(clear_catalogue(db_session))
    first = seed_programs(db_session)
    second = seed_programs(db_session)
    assert first == len(PROGRAMS)
    assert second == 0, "re-running the seed must not duplicate rows"


def test_seed_does_not_duplicate_sources_or_prerequisites(db_session, require_db):
    """Idempotency has to hold for the child rows too, not just the program count."""
    applications_displaced_mid_run.extend(clear_catalogue(db_session))
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


def test_seeded_values_still_mirror_the_typescript_source(db_session, require_db, tmp_path):
    """Every seeded value must equal the value web/lib/programs.ts carries today.

    Nothing else in the suite ties a stored value to the file the seed was transcribed from, so a
    changed mark, a dropped prerequisite or a truncated url used to leave the build green. The
    comparison itself lives in scripts/verify-programs-mirror.cjs: it imports the TypeScript through
    Node's own type stripping, so the expected values come from the source of truth rather than from
    a second hand-copied table, and it fails loudly when it finds nothing to compare.

    The catalogue is cleared first because ``seed_programs`` skips any program id that already
    exists. Without that, a row left behind by an earlier run — or by a different tree — would be
    read back and compared, and the verdict would describe the database's history instead of
    api/app/seed.py. Clearing means the rows read back are the ones this run of the seed wrote.
    """
    applications_displaced_mid_run.extend(clear_catalogue(db_session))
    seed_programs(db_session)

    # `Program` has no `source` relationship, so the url is read from the row the program points at.
    source_urls = dict(db_session.execute(select(Source.id, Source.url)).all())
    dump = {
        "programs": [
            {
                "id": program.id,
                "city": program.city,
                "degree_level": program.degree_level,
                "field": program.field,
                "duration": program.duration,
                "minimum_mark": json_number(program.minimum_mark),
                "non_211_minimum_mark": json_number(program.non_211_minimum_mark),
                "requires_cognate": program.requires_cognate,
                "english_requirement": program.english_requirement,
                "source_url": source_urls.get(program.source_id),
                "prerequisites": [
                    row.label
                    for row in sorted(program.prerequisites, key=lambda row: row.sort_order)
                ],
            }
            for program in db_session.execute(select(Program).order_by(Program.id)).scalars()
        ]
    }
    # Nothing here filters the rows: when the database holds no program the dump is empty and the
    # guard reports that as a failure, so a broken seed can never look like a clean comparison.
    dump_path = tmp_path / "programs-from-database.json"
    dump_path.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        ["node", str(MIRROR_GUARD), str(dump_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{MIRROR_GUARD.name} rejected the seeded values\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "MISMATCH" not in result.stdout
