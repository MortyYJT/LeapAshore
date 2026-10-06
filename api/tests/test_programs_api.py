"""Tests for the public program catalogue endpoint.

These run against the shared development database, so `seed_programs` is not enough on its own to
guarantee the rows these tests read: it skips any program id that already exists, which means a
row left behind by an earlier run — or by a different tree — is what gets served. The tests that
read the catalogue therefore assert on shape and on the keys the frontend reads, not on exact
values, and none of them leave a row deleted behind.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.main import app
from app.models.program import Program, University
from app.models.source import Source
from app.routers.programs import list_programs
from app.seed import seed_programs


def test_lists_every_seeded_program_with_its_source(require_db, db_session):
    seed_programs(db_session)
    response = TestClient(app).get("/api/programs")
    assert response.status_code == 200

    programs = response.json()
    assert len(programs) >= 6
    first = programs[0]
    assert set(first) >= {"id", "name", "universityName", "source", "dataStatus"}
    assert first["source"]["url"].startswith("https://")
    assert first["source"]["status"] == "待核验"


def test_filters_by_field(require_db, db_session):
    seed_programs(db_session)
    response = TestClient(app).get("/api/programs", params={"field": "计算机与数据"})
    assert response.status_code == 200
    assert all(p["field"] == "计算机与数据" for p in response.json())


def test_a_field_that_matches_nothing_is_an_empty_list(require_db, db_session):
    """No match is an answer, not a failure: the frontend renders an empty catalogue."""
    seed_programs(db_session)
    response = TestClient(app).get("/api/programs", params={"field": "不存在的专业方向"})
    assert response.status_code == 200
    assert response.json() == []


def test_the_catalogue_needs_no_client_cookie(require_db, db_session):
    """This endpoint serves reference data, not applicant data, so it must not mint a subject.

    `/api/profile` hands out an `offerpilot_client` cookie on first contact. If the catalogue did
    the same, merely opening the school list would create an anonymous applicant row.
    """
    seed_programs(db_session)
    client = TestClient(app)
    response = client.get("/api/programs")
    assert response.status_code == 200
    assert "offerpilot_client" not in client.cookies
    assert "set-cookie" not in {key.lower() for key in response.headers}


def test_the_database_refuses_a_program_whose_source_does_not_exist(require_db, db_session):
    """The "program without its source" state is prevented by the schema, not merely by the router.

    `programs.source_id` is a foreign key, so deleting a source a program still cites is rejected
    by PostgreSQL. That is worth pinning down: it is the guarantee that makes the router's
    missing-source guard a backstop rather than the everyday path, and a later migration that
    relaxes the constraint would break this test instead of silently letting programs lose their
    provenance.
    """
    seed_programs(db_session)
    program_id = db_session.execute(select(Program.id).order_by(Program.id)).scalars().first()
    source_id = db_session.get(Program, program_id).source_id
    assert source_id is not None, "the seed must have attached a source"

    with SessionLocal() as remove:
        with pytest.raises(IntegrityError):
            remove.execute(Source.__table__.delete().where(Source.__table__.c.id == source_id))
            remove.commit()
        remove.rollback()

    # The rejected delete left the catalogue whole.
    with SessionLocal() as check:
        assert check.get(Source, source_id) is not None


def test_a_program_whose_source_row_is_gone_fails_loudly():
    """The router's backstop for a program whose source row cannot be read.

    That state cannot be reached through PostgreSQL while the foreign key holds, so this drives
    the endpoint with a session stub instead of pretending a database could produce it. It still
    pins the decision: refusing to answer beats `source: null` (a program with no provenance) and
    beats dropping the row (a catalogue that shrinks with no explanation).
    """
    orphan = Program(
        id="orphan-program",
        university_id="unsw",
        name="没有来源的项目",
        data_status="待核验",
        source_id="src-that-does-not-exist",
    )
    orphan.university = University(id="unsw", name="新南威尔士大学")

    session = MagicMock()
    session.execute.return_value.scalars.return_value = iter([orphan])
    session.get.return_value = None

    with pytest.raises(HTTPException) as raised:
        list_programs(session, field=None)

    assert raised.value.status_code == 500
    assert "orphan-program" in raised.value.detail


def test_the_wire_format_uses_the_frontend_key_names(require_db, db_session):
    """Task 8 feeds this response into `Program` in web/lib/types.ts.

    The camelCase keys are the contract, not a detail. This asserts the names the frontend reads
    that the endpoint already answers; the deliberate differences are listed in the report rather
    than asserted here, because a name this endpoint does not carry has no response key to check.
    """
    seed_programs(db_session)
    body = TestClient(app).get("/api/programs").json()
    assert body, "the catalogue must not be empty"

    for key in (
        "id",
        "name",
        "universityName",
        "city",
        "degreeLevel",
        "field",
        "duration",
        "minimumMark",
        "non211MinimumMark",
        "requiresCognate",
        "englishRequirement",
        "dataStatus",
    ):
        assert key in body[0], key

    for key in ("url", "title", "status"):
        assert key in body[0]["source"], key
