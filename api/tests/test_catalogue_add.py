"""Adding a school-library program to 我的申请 in one step (`POST /api/application-records/catalog`).

The record is the program's portfolio row, so the tests read it back through both the records and the
portfolio routes. The catalogue fixture gives the first program two collected deadlines and the second
one; they are made up for these tests.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import app
from app.models.application import Application
from app.models.task import TaskEvent
from tests.test_application_tools import OTHER_SOURCE, SOURCE, catalogue  # noqa: F401
from tests.versioned import delete_record, patch_record, put_portfolio

pytestmark = pytest.mark.usefixtures("require_db")


def add(client: TestClient, program: str, tier: str | None = None):
    return client.post("/api/application-records/catalog", json={"programId": program, "tier": tier})


def rows_of(client: TestClient, program: str) -> int:
    subject = client.cookies.get("leapashore_client")
    with SessionLocal() as s:
        return s.scalar(
            select(func.count()).select_from(Application)
            .where(Application.client_id == subject, Application.program_id == program)
        )


def test_one_step_add_shows_the_catalogue_date_as_collected_and_unchecked(catalogue):
    client = TestClient(app)
    response = add(client, catalogue["first"], "冲")
    assert response.status_code == 201
    record = response.json()
    assert record["id"] == f"catalog:{catalogue['first']}"
    assert record["programId"] == catalogue["first"] and record["status"] == "considering"
    # The catalogue's next date with its own page, marked as collected and not yet checked.
    assert record["deadline"] == catalogue["round1_date"].isoformat()
    assert record["sourceUrl"] == SOURCE
    assert record["deadlineOrigin"] == "collected" and record["checkedAt"] is None
    assert record["round"] is None
    assert client.get("/api/application-records").json() == [record]
    portfolio = client.get("/api/applications").json()
    assert [(row["programId"], row["tier"], row["needsReview"], row["origin"]) for row in portfolio] == [
        (catalogue["first"], "冲", False, "user")
    ]
    # Nothing was copied into the applicant's own deadline fields: the date stays the catalogue's.
    assert portfolio[0]["officialDeadline"] is None and portfolio[0]["deadlineSourceUrl"] is None


def test_a_second_add_returns_the_stored_record_and_writes_nothing(catalogue):
    client = TestClient(app)
    first = add(client, catalogue["second"]).json()
    with SessionLocal() as s:
        events = s.scalar(select(func.count()).select_from(TaskEvent).where(TaskEvent.client_id == client.cookies.get("leapashore_client")))
    again = add(client, catalogue["second"], "保")
    assert again.status_code == 200
    assert again.json() == first
    assert rows_of(client, catalogue["second"]) == 1
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(TaskEvent).where(TaskEvent.client_id == client.cookies.get("leapashore_client"))) == events
    # The replay did not move the band either.
    assert client.get("/api/applications").json()[0]["tier"] == "稳"


def test_without_a_band_the_row_is_flagged_for_review(catalogue):
    client = TestClient(app)
    record = add(client, catalogue["second"]).json()
    assert record["deadline"] == catalogue["other_date"].isoformat() and record["sourceUrl"] == OTHER_SOURCE
    row = client.get("/api/applications").json()[0]
    assert row["tier"] == "稳" and row["needsReview"] is True
    # A stand-in band the caller flags (the tiers found the applicant short) is stored flagged too.
    other = TestClient(app)
    assert other.post(
        "/api/application-records/catalog", json={"programId": catalogue["second"], "tier": "冲", "needsReview": True}
    ).status_code == 201
    assert [(r["tier"], r["needsReview"]) for r in other.get("/api/applications").json()] == [("冲", True)]


def test_a_program_already_chosen_keeps_its_edits(catalogue):
    client = TestClient(app)
    assert put_portfolio(client, [{"programId": catalogue["first"], "tier": "保"}]).status_code == 200
    key = f"catalog:{catalogue['first']}"
    edited = patch_record(client, key, {"status": "applying", "round": "R2"}).json()
    response = add(client, catalogue["first"], "冲")
    assert response.status_code == 200
    assert response.json() == edited
    assert client.get("/api/applications").json()[0]["tier"] == "保"


def test_an_added_program_can_be_taken_back_and_added_again(catalogue):
    client = TestClient(app)
    record = add(client, catalogue["first"]).json()
    assert delete_record(client, record["id"]).status_code == 204
    assert client.get("/api/application-records").json() == []
    assert add(client, catalogue["first"]).status_code == 201
    assert rows_of(client, catalogue["first"]) == 1


def test_unknown_programs_and_stray_fields_are_refused(catalogue):
    client = TestClient(app)
    assert add(client, "no-such-program").status_code == 404
    assert client.post("/api/application-records/catalog", json={"programId": catalogue["first"], "tier": "中"}).status_code == 422
    assert client.post(
        "/api/application-records/catalog", json={"programId": catalogue["first"], "deadline": "2027-01-01"}
    ).status_code == 422
    assert client.get("/api/application-records").json() == []
