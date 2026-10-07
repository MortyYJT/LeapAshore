import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.deps import COOKIE_NAME
from app.main import app
from app.models.roadmap import MaterialTemplate
from app.seed_roadmap import MATERIALS, VISA_MATERIALS, seed_roadmap


@pytest.fixture(autouse=True)
def remove_the_roadmap_definition_these_tests_seed(
    clear_the_roadmap_definition_after_the_test,
):
    """Delete the definition again after each test here, the way the seed module does.

    ``seed_roadmap`` commits and the ``db_session`` fixture's teardown only rolls back, so without
    this the seven phases, their thirty-three materials and the Genuine Student source stay in the
    shared development database for the rest of the run. ``tests/conftest.py`` removes the
    definition once, before the session starts, precisely because two later modules hold values the
    seed owns: ``test_roadmap_model.py`` inserts the keys ``selection`` and ``aca-transcript``, and
    ``test_sources.py`` inserts the Genuine Student url, which is unique. This module is collected
    before both of them, so seeding without cleaning up makes them fail on a unique violation for a
    reason that has nothing to do with what they test — measured, not assumed:
    ``test_roadmap_model.py::test_phase_and_material_round_trip`` goes red with
    ``IntegrityError: duplicate key value violates unique constraint "roadmap_phases_pkey"``, and
    only the fact that ``test_seed_roadmap.py`` happens to clear the definition before
    ``test_sources.py`` is collected keeps the other one green.

    The sweep itself lives in ``tests.conftest`` as a non-autouse fixture both seeding modules
    request, because as an autouse fixture there it would also run for ``test_roadmap_model.py``
    and delete the very rows that module asserts on. This wrapper exists only to make the sweep
    autouse inside this module and to carry this module's reason for needing it; the session-scoped
    fixture in ``tests/conftest.py`` restores the definition once the whole run is over.
    """


def test_returns_every_phase_and_material(require_db, db_session):
    seed_roadmap(db_session)
    body = TestClient(app).get("/api/roadmap").json()

    assert len(body["phases"]) == 7
    assert len(body["materials"]) == 33
    assert body["phases"][0]["key"] == "selection"
    assert body["phases"][-1]["key"] == "visa"
    assert set(body["phases"][0]) == {"key", "title", "subtitle", "offsetDays", "sortOrder"}
    assert set(body["materials"][0]) >= {"key", "phase", "title", "detail", "appliesTo"}


def test_visa_materials_carry_their_source(require_db, db_session):
    """An authored requirement must show where it came from; the six transcribed phases need not."""
    seed_roadmap(db_session)
    body = TestClient(app).get("/api/roadmap").json()
    visa = [m for m in body["materials"] if m["phase"] == "visa"]
    assert visa, "the visa phase must expose materials"
    assert all(m.get("source") and m["source"]["url"].startswith("https://") for m in visa)
    assert all(m["source"]["status"] == "待核验" for m in visa)


def test_phases_come_back_in_timeline_order(require_db, db_session):
    seed_roadmap(db_session)
    body = TestClient(app).get("/api/roadmap").json()
    offsets = [p["offsetDays"] for p in body["phases"]]
    assert offsets == sorted(offsets, reverse=True), "phases must be ordered by offset, not by key"


def test_materials_come_back_grouped_by_phase_in_timeline_order(require_db, db_session):
    """The stated material order is ``(phase order, material sort_order)``, and it holds on the wire.

    ``test_phases_come_back_in_timeline_order`` covers the phases list alone. A sort key that
    dropped the phase — ``(material.sort_order, material.key)``, say — returns the same thirty-three
    materials in a list that still looks plausible, because every phase's first material carries
    ``sort_order`` 0 and every phase's are numbered from there: the phases simply interleave, and
    the frontend renders selection, academic, selection, academic. Nothing else in the suite asserts
    the order the materials arrive in, so the phase each one arrives under is asserted here, against
    the counts the seed carries.
    """
    seed_roadmap(db_session)
    body = TestClient(app).get("/api/roadmap").json()

    expected = (
        ["selection"] * 5
        + ["academic"] * 5
        + ["language"] * 4
        + ["specialized"] * 6
        + ["submission"] * 5
        + ["decision"] * 6
        + ["visa"] * 2
    )
    assert [material["phase"] for material in body["materials"]] == expected, (
        "materials must arrive grouped under their phase, in the phases list's own order"
    )


def test_materials_within_each_phase_come_back_in_their_authored_order(require_db, db_session):
    """The other half of the stated order: within a phase, ``sort_order`` decides, not the key.

    ``test_materials_come_back_grouped_by_phase_in_timeline_order`` pins which phase each material
    arrives under and says nothing about the order inside a phase. A route sorting by
    ``(phase order, material.key)`` keeps that test green and still changes what the applicant sees:
    every phase's requirements come back in alphabetical order — ``sel-check`` before ``sel-goal`` —
    and the frontend keeps the array position as the order and never re-sorts, so nothing notices.
    ``check-roadmap-mirror`` compares the constants with the snapshot and not with a response, so it
    cannot notice either. This is the material half of ``test_phases_come_back_in_timeline_order``,
    and it is what makes the order the applicant sees an asserted fact rather than something the seed
    happens to make alphabetical (it is not).

    The expected order is the seed's own, read in its own order, so a reordering there is a
    reordering here by construction. That is deliberate: the seed is what mirrors
    ``web/lib/roadmap.ts``, and the mirror guard keeps *that* comparison honest. What is under test
    is that the route preserves the authored order instead of inventing one of its own.

    The second assertion reads the same fact from the wire alone: within a phase the served
    ``sortOrder`` ascends. It would survive a reordered seed, and it refuses any in-phase order that
    is not the rule the route states.
    """
    seed_roadmap(db_session)
    body = TestClient(app).get("/api/roadmap").json()

    authored: dict[str, list[str]] = {}
    for row in MATERIALS + VISA_MATERIALS:
        authored.setdefault(row["phase"], []).append(row["key"])
    served: dict[str, list[str]] = {}
    for material in body["materials"]:
        served.setdefault(material["phase"], []).append(material["key"])

    assert served == authored, "materials must arrive within their phase in the seed's own order"

    for phase in served:
        orders = [m["sortOrder"] for m in body["materials"] if m["phase"] == phase]
        assert orders == sorted(orders) and len(set(orders)) == len(orders), (
            f"{phase} must arrive in ascending sort_order, one material per position: {orders}"
        )


def test_materials_without_a_source_serve_null(require_db, db_session):
    """``source: null`` is the schema module's stated point, and it has to survive the wire.

    The visa test cannot see this: a route that fabricated a ``SourceRef`` for the materials whose
    ``source_id`` is ``NULL`` — a blank citation, or a second copy of the visa page — would leave
    every other test in this module green while claiming provenance nobody established. The nulls
    are asserted against the rows that imply them rather than against a second hand-written list,
    so a missing row cannot make the comparison pass by being empty on both sides.
    """
    seed_roadmap(db_session)
    body = TestClient(app).get("/api/roadmap").json()

    without_a_source_row = set(
        db_session.execute(
            select(MaterialTemplate.key).where(MaterialTemplate.source_id.is_(None))
        ).scalars()
    )
    assert without_a_source_row == {row["key"] for row in MATERIALS}, (
        "the seed attaches a source to the visa pair only, so the transcribed materials are the "
        "ones with no source row"
    )

    served_without_a_source = {
        material["key"] for material in body["materials"] if material["source"] is None
    }
    assert served_without_a_source == without_a_source_row, (
        "a material with no source row must serialise as null, not as an object"
    )
    assert len(served_without_a_source) == 31, "thirty-one of the thirty-three have no source"


def test_sets_a_cookie_only_for_the_tasks_it_returns(require_db, db_session):
    """The definition is shared configuration, the tasks are not, and the cookie names the subject.

    This assertion used to say the route sets no cookie at all, and that was right while the response
    was the definition alone: reading or minting a cookie for shared configuration would hand a
    visitor a subject they never asked for and imply the timeline is theirs. The route now also
    returns the caller's own task rows, which belong to exactly one subject, so it has to resolve a
    subject — and a first-time visitor has no cookie to present, so the response has to mint one.
    Deleting the assertion would have left that change unstated; what replaces it is the narrower
    fact that is still true: the *definition* halves are identical for every caller and never depend
    on the cookie, while the tasks half is addressed by it.
    """
    seed_roadmap(db_session)
    # One client, so the cookie the first response sets is what the second request presents: that is
    # what makes the pair below about the same subject rather than about two anonymous visitors.
    client = TestClient(app)
    first = client.get("/api/roadmap")
    assert first.status_code == 200
    assert "set-cookie" in {k.lower() for k in first.headers}, (
        "the route returns applicant-owned tasks, so it must identify the subject it returns them for"
    )
    assert first.json()["tasks"] == [], "a subject minted by this request owns no rows yet"
    assert COOKIE_NAME in client.cookies, "the minted subject was not the one the response named"

    # The definition half is identical for every caller, cookie or not.
    second = client.get("/api/roadmap")
    assert second.json()["phases"] == first.json()["phases"]
    assert second.json()["materials"] == first.json()["materials"]
    assert second.json()["tasks"] == []
