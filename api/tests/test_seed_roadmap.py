"""Tests for the roadmap definition seed.

The fixtures run against the shared development database, as the rest of the suite does, so every
test here clears the two roadmap tables first: ``seed_roadmap`` skips any key that already exists,
which means a row left behind by an earlier run — or by a different tree — would be read back and
compared instead of the rows this run wrote. The autouse fixture below removes the same rows again
afterwards, including the Genuine Student source, so the suite neither depends on nor leaves behind
the seeded definition. ``tests/conftest.py`` removes it once before the session starts as well,
because the seed now owns keys and a url that two other modules hold as fixed values: without that,
``make seed`` followed by ``make test`` would fail in ``test_roadmap_model.py`` and
``test_sources.py`` for a reason that has nothing to do with what they test.

The last test hands the seeded rows to ``scripts/verify-roadmap-mirror.cjs``, the guard that keeps
the definition from drifting away from ``web/lib/roadmap.ts``.

The module carries 31 transcribed materials, not the 29 the M2a plan records, and the difference is
knowledge, not a choice. ``web/lib/roadmap.ts`` holds 5 + 5 + 4 + 6 + 5 + 6 = 31 entries. The 29 is
what the frontend's own test ``counts 29 materials for the taught-master default`` asserts, and that
is the number of materials *visible* to the default profile: ``spe-portfolio`` (``appliesTo:
"portfolio"``) and ``spe-research`` (``appliesTo: "research"``) are filtered out for a taught master.
Both are real requirements belonging to other applicants, and ``applies_to`` is the column that keeps
them expressible, so all 31 entries are transcribed and the guard reports 31.
"""

import json
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.seed_roadmap import MATERIALS, PHASES, VISA_MATERIALS, seed_roadmap
from tests.conftest import clear_the_roadmap_definition, database_is_reachable

PHASE_KEYS = [
    "selection",
    "academic",
    "language",
    "specialized",
    "submission",
    "decision",
    "visa",
]

# tests/ -> api/ -> the repository root, where the guard and the frontend data live.
REPO_ROOT = Path(__file__).resolve().parents[2]
MIRROR_GUARD = REPO_ROOT / "scripts" / "verify-roadmap-mirror.cjs"


def _clear(session):
    for row in session.execute(select(MaterialTemplate)).scalars():
        session.delete(row)
    for row in session.execute(select(RoadmapPhase)).scalars():
        session.delete(row)
    session.commit()


@pytest.fixture(autouse=True)
def remove_the_roadmap_definition_these_tests_write():
    """Leave the shared development database as it was found.

    The Genuine Student source goes with the phases and the materials. It is not a row these tests
    invented — the seed creates it — but ``test_sources.py`` inserts the same url to prove a new
    source starts unverified, and ``sources.url`` is unique, so leaving the seeded row behind would
    make that test fail on a unique violation. The two modules run in different orders depending on
    whether the whole suite or one file is selected, so each removes what it needs to.
    """
    yield
    if not database_is_reachable():
        return
    with SessionLocal() as session:
        clear_the_roadmap_definition(session)
        session.commit()


def test_seed_is_idempotent(db_session, require_db):
    _clear(db_session)
    first = seed_roadmap(db_session)
    second = seed_roadmap(db_session)
    assert first[0] == 7 and first[1] > 0
    assert second == (0, 0), "re-running the seed must not duplicate rows"


def test_every_phase_is_present(db_session, require_db):
    _clear(db_session)
    seed_roadmap(db_session)
    keys = set(db_session.execute(select(RoadmapPhase.key)).scalars())
    assert set(PHASE_KEYS) <= keys


def test_visa_phase_exists_with_materials(db_session, require_db):
    """The seventh phase is the one the Genuine Student work hangs off."""
    _clear(db_session)
    seed_roadmap(db_session)
    assert db_session.get(RoadmapPhase, "visa") is not None
    count = db_session.execute(
        select(func.count()).select_from(MaterialTemplate).where(MaterialTemplate.phase == "visa")
    ).scalar()
    assert count > 0


def test_every_material_points_at_a_real_phase(db_session, require_db):
    _clear(db_session)
    seed_roadmap(db_session)
    phase_keys = set(db_session.execute(select(RoadmapPhase.key)).scalars())
    orphans = [
        m.key
        for m in db_session.execute(select(MaterialTemplate)).scalars()
        if m.phase not in phase_keys
    ]
    assert orphans == [], f"materials with an unknown phase: {orphans}"


def test_offsets_are_positive_and_descending(db_session, require_db):
    """Later phases must suggest later dates; a sign error would silently invert the timeline."""
    _clear(db_session)
    seed_roadmap(db_session)
    offsets = [
        p.offset_days
        for p in db_session.execute(
            select(RoadmapPhase).order_by(RoadmapPhase.sort_order)
        ).scalars()
    ]
    assert all(o > 0 for o in offsets)
    assert offsets == sorted(offsets, reverse=True)


def test_the_seed_writes_exactly_the_definition_it_carries(db_session, require_db):
    """Every constant in the module reaches a row, and no row exists without one.

    This is what catches a transcription that quietly drops an entry: the frontend holds 31
    materials and the seed must carry all of them, not the 29 the plan's hand count recorded.
    """
    _clear(db_session)
    seed_roadmap(db_session)

    stored_phases = set(db_session.execute(select(RoadmapPhase.key)).scalars())
    assert stored_phases == {row["key"] for row in PHASES}

    stored_materials = set(db_session.execute(select(MaterialTemplate.key)).scalars())
    expected = {row["key"] for row in MATERIALS} | {row["key"] for row in VISA_MATERIALS}
    assert stored_materials == expected


def test_only_the_visa_materials_cite_a_source(db_session, require_db):
    """The six transcribed phases are placeholder data with no official page yet.

    Attaching a source to them would claim a citation nobody made.
    """
    _clear(db_session)
    seed_roadmap(db_session)
    sourced = {
        m.phase
        for m in db_session.execute(
            select(MaterialTemplate).where(MaterialTemplate.source_id.is_not(None))
        ).scalars()
    }
    assert sourced == {"visa"}


def test_seeded_values_still_mirror_the_typescript_source(db_session, require_db, tmp_path):
    """Every seeded value must equal the value ``web/lib/roadmap.ts`` carries today.

    Nothing else in the suite ties a stored value to the file the seed was transcribed from, so a
    changed offset, a reworded title or a dropped material used to leave the build green. The
    comparison itself lives in ``scripts/verify-roadmap-mirror.cjs``: it imports the TypeScript
    through Node's own type stripping, so the expected values come from the source of truth rather
    than from a second hand-copied table, and it fails loudly when it finds nothing to compare.

    The dump carries every row the seed writes, including the visa phase and its materials. The
    guard skips those on purpose — they are authored in ``api/app/seed_roadmap.py`` and have no
    counterpart in the TypeScript — and the tests above cover them instead.
    """
    _clear(db_session)
    seed_roadmap(db_session)

    dump = {
        "phases": [
            {
                "key": phase.key,
                "title": phase.title,
                "subtitle": phase.subtitle,
                "offset_days": phase.offset_days,
                "sort_order": phase.sort_order,
            }
            for phase in db_session.execute(
                select(RoadmapPhase).order_by(RoadmapPhase.key)
            ).scalars()
        ],
        "materials": [
            {
                "key": material.key,
                "phase": material.phase,
                "title": material.title,
                "detail": material.detail,
                "applies_to": material.applies_to,
                "sort_order": material.sort_order,
            }
            for material in db_session.execute(
                select(MaterialTemplate).order_by(MaterialTemplate.key)
            ).scalars()
        ],
    }
    # Nothing here filters the rows: when the tables are empty the dump is empty and the guard
    # reports that as a failure, so a broken seed can never look like a clean comparison.
    dump_path = tmp_path / "roadmap-from-database.json"
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
