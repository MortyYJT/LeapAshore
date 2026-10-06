import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.seed_roadmap import seed_roadmap
from tests.conftest import clear_the_roadmap_definition, database_is_reachable


@pytest.fixture(autouse=True)
def remove_the_roadmap_definition_these_tests_seed():
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

    It lives here rather than in ``conftest.py`` because it is only correct for a module whose tests
    seed: as an autouse fixture there it would also run for ``test_roadmap_model.py`` and delete the
    very rows that module asserts on. The rows go first and the Genuine Student source goes with
    them, because ``material_templates.source_id`` points at it — ``clear_the_roadmap_definition``
    documents that order. The session-scoped fixture in ``tests/conftest.py`` restores the
    definition once the whole run is over.
    """
    yield
    if not database_is_reachable():
        return
    with SessionLocal() as session:
        clear_the_roadmap_definition(session)
        session.commit()


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


def test_does_not_require_a_cookie(require_db, db_session):
    """The definition is shared configuration, not applicant data."""
    seed_roadmap(db_session)
    response = TestClient(app).get("/api/roadmap")
    assert response.status_code == 200
    assert "set-cookie" not in {k.lower() for k in response.headers}
