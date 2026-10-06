"""Tests for the placeholder catalogue seed.

The fixtures run against the shared development database. The tests that assert on how many rows a
run adds — and the last one, which compares stored values against the frontend source — clear the
catalogue first, so they cannot be answered by whatever a developer happened to leave in the
database. The rest seed on top of the existing rows and assert only on the seeded rows, which the
seed's own idempotency makes safe.

The last test hands the seeded rows to scripts/verify-programs-mirror.cjs, the guard that keeps the
seed and web/lib/programs.ts from drifting apart.
"""

import json
import subprocess
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, func, select

from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source, SourceStatus, SourceVersion
from app.seed import PROGRAMS, UNIVERSITIES, seed_programs

PROGRAM_IDS = [row["id"] for row in PROGRAMS]
UNIVERSITY_IDS = [row["id"] for row in UNIVERSITIES]

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
    clear_catalogue(db_session)
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
