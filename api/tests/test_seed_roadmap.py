"""Tests for the roadmap definition seed.

The fixtures run against the shared development database, as the rest of the suite does, so every
test here clears the two roadmap tables first: ``seed_roadmap`` skips any key that already exists,
which means a row left behind by an earlier run — or by a different tree — would be read back and
compared instead of the rows this run wrote. The autouse fixture below removes the same rows again
afterwards, including the Genuine Student source, and the session-scoped fixture in
``tests/conftest.py`` restores the definition once the whole run is over, so a ``make test`` leaves
the shared database holding the definition ``make seed`` produces rather than an empty timeline.
``tests/conftest.py`` removes it once before the session starts as well, because the seed now owns
keys and a url that two other modules hold as fixed values: without that, ``make seed`` followed by
``make test`` would fail in ``test_roadmap_model.py`` and ``test_sources.py`` for a reason that has
nothing to do with what they test.

The database-backed tests come last. ``test_seeded_values_still_mirror_the_typescript_source`` hands
the seeded rows to ``scripts/verify-roadmap-mirror.cjs``, the guard that keeps the definition from
drifting away from ``web/lib/roadmap.ts``, and it needs the database, so it skips with the container
down; ``test_the_constants_match_the_committed_snapshot`` carries the same comparison without one,
so a wrong constant is still visible when the container is down and both the guard and every test
that reads a row step aside.

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
SNAPSHOT = REPO_ROOT / "scripts" / "roadmap-definition.snapshot.json"

# The fields scripts/verify-roadmap-mirror.cjs compares, spelled here the way the snapshot and the
# tables spell them. They are duplicated on purpose: a snapshot that renamed a field must fail as a
# changed value rather than as a missing one, and if this list and the guard's ever disagree the
# containerless test below stops finding the field and says so by name.
PHASE_FIELDS = ("key", "title", "subtitle", "offset_days", "sort_order")
MATERIAL_FIELDS = ("key", "phase", "title", "detail", "applies_to", "sort_order")


def _clear(session):
    for row in session.execute(select(MaterialTemplate)).scalars():
        session.delete(row)
    for row in session.execute(select(RoadmapPhase)).scalars():
        session.delete(row)
    session.commit()


@pytest.fixture(autouse=True)
def remove_the_roadmap_definition_these_tests_write():
    """Remove the rows these tests write, and the Genuine Student source with them.

    The rows go first, exactly as before these tests wrote anything. They are removed rather than
    restored here because the definition has to stay empty for the whole run: ``test_sources.py``
    inserts the Genuine Student url, which is unique, and ``test_roadmap_model.py`` inserts the keys
    ``selection`` and ``aca-transcript``, so a seeded database reaching either module makes it fail
    on a unique violation for a reason that has nothing to do with what it tests. That is also why
    ``tests/conftest.py`` removes the definition once before the session starts.

    The Genuine Student source is not a row these tests invented — the seed creates it — but it
    belongs to the definition, so it leaves with the phases and the materials. Restoring the
    definition is the session-scoped fixture's job in ``tests/conftest.py``: it finalises after this
    one, and it is what makes a ``make test`` leave a seeded database rather than an empty timeline.
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


def test_the_constants_match_the_committed_snapshot():
    """The seed's constants still carry the definition the snapshot was generated from.

    This is the only check in the file that needs no database, and it exists for the case where
    there is none: ``require_db`` skips every test above, and ``make test`` runs
    ``check-roadmap-mirror`` with no dump, which compares ``web/lib/roadmap.ts`` against the
    committed snapshot. A snapshot regenerated from the same TypeScript therefore compares equal to
    itself, and a seed constant that was changed, or mistyped, is compared to nothing at all. The
    snapshot holds the six transcribed phases and their thirty-one materials; the visa phase and its
    two materials are authored in the seed and have no counterpart there, so they are left out.
    """
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    recorded_phases = {row["key"]: row for row in snapshot["phases"]}
    recorded_materials = {row["key"]: row for row in snapshot["materials"]}
    # The visa phase is authored in the seed, so it is the one key the snapshot has never carried.
    carried_phases = {row["key"]: row for row in PHASES if row["key"] != "visa"}
    carried_materials = {row["key"]: row for row in MATERIALS}

    assert len(carried_phases) == len(recorded_phases) == 6
    assert len(carried_materials) == len(recorded_materials) == 31
    for carried, recorded, fields, kind in (
        (carried_phases, recorded_phases, PHASE_FIELDS, "phase"),
        (carried_materials, recorded_materials, MATERIAL_FIELDS, "material"),
    ):
        for key, row in carried.items():
            for field in fields:
                assert row[field] == recorded[key][field], (
                    f"{SNAPSHOT.name}: the {kind} {key}.{field} is {row[field]!r} in "
                    f"app/seed_roadmap.py and {recorded[key][field]!r} in the snapshot"
                )


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
