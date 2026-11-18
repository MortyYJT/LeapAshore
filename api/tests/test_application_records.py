from fastapi.testclient import TestClient
from app.main import app


def test_manual_application_round_date_and_ownership(require_db):
    owner, stranger = TestClient(app), TestClient(app)
    response = owner.post(
        "/api/application-records",
        json={"school": "Example University", "name": "Example MSc"},
    )
    assert response.status_code == 201
    record = response.json()
    key = record["id"]
    assert record["deadline"] is None
    assert stranger.get("/api/application-records").json() == []
    assert (
        stranger.patch(
            f"/api/application-records/{key}", json={"status": "submitted"}
        ).status_code
        == 404
    )
    assert stranger.delete(f"/api/application-records/{key}").status_code == 404
    response = owner.patch(
        f"/api/application-records/{key}",
        json={"deadline": "2027-01-15", "round": "Round 1", "materialsReady": True},
    )
    assert response.status_code == 200
    assert response.json()["checkedAt"] is None
    assert (
        owner.patch(
            f"/api/application-records/{key}", json={"confirmDeadline": True}
        ).status_code
        == 422
    )
    response = owner.patch(
        f"/api/application-records/{key}",
        json={"sourceUrl": "https://example.edu/apply", "confirmDeadline": True},
    )
    assert response.status_code == 200 and response.json()["checkedAt"]
    changed = owner.patch(
        f"/api/application-records/{key}", json={"round": "Round 2"}
    ).json()
    assert changed["checkedAt"] is None
    assert changed["materialsReady"] is True
    assert owner.get("/api/application-records").json()[0]["round"] == "Round 2"
    assert owner.put("/api/applications", json={"rows": []}).status_code == 200
    assert len(owner.get("/api/application-records").json()) == 1
    assert owner.delete(f"/api/application-records/{key}").status_code == 204
    assert owner.get("/api/application-records").json() == []


def test_application_record_validation(require_db):
    client = TestClient(app)
    assert (
        client.post(
            "/api/application-records", json={"school": " ", "name": "MSc"}
        ).status_code
        == 422
    )
    response = client.post(
        "/api/application-records", json={"school": "Example", "name": "MSc"}
    )
    assert response.status_code == 201
    key = response.json()["id"]
    assert (
        client.patch(
            f"/api/application-records/{key}", json={"sourceUrl": "javascript:alert(1)"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/application-records/{key}", json={"status": "invented"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/application-records/{key}",
            json={"deadline": None, "confirmDeadline": True},
        ).status_code
        == 422
    )


def test_catalogue_selection_round_edits_preserve_legacy_contract(
    require_db, db_session
):
    from app.seed import seed_programs
    from tests.test_seed import PROGRAM_IDS

    seed_programs(db_session)
    client = TestClient(app)
    program = PROGRAM_IDS[0]
    assert (
        client.put(
            "/api/applications", json={"rows": [{"programId": program, "tier": "稳"}]}
        ).status_code
        == 200
    )
    records = client.get("/api/application-records").json()
    assert len(records) == 1
    record = records[0]
    assert record["programId"] == program
    assert (
        client.patch(
            f"/api/application-records/{record['id']}",
            json={
                "status": "submitted",
                "deadline": "2027-02-01",
                "sourceUrl": "https://example.edu/apply",
                "round": "R1",
                "confirmDeadline": True,
            },
        ).status_code
        == 200
    )
    legacy = client.get("/api/applications").json()[0]
    assert (
        legacy["status"] == "submitted" and legacy["officialDeadline"] == "2027-02-01"
    )
    assert (
        client.put(
            "/api/applications", json={"rows": [{"programId": program, "tier": "冲"}]}
        ).status_code
        == 200
    )
    assert client.get("/api/application-records").json()[0]["round"] == "R1"
    assert client.delete(f"/api/application-records/{record['id']}").status_code == 204
    assert client.get("/api/applications").json() == []


def test_manual_plans_move_with_anonymous_subject_and_cascade(require_db, db_session):
    from uuid import uuid4
    from sqlalchemy import select, delete
    from app.models.application_plan import ApplicationPlan
    from app.models.client import Client
    from app.services.accounts import merge_subject, new_subject

    source, target = str(uuid4()), str(uuid4())
    new_subject(db_session, source)
    new_subject(db_session, target)
    plan = ApplicationPlan(
        id=str(uuid4()), client_id=source, school="Example", name="MSc"
    )
    db_session.add(plan)
    db_session.commit()
    merge_subject(db_session, source, target)
    db_session.commit()
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(ApplicationPlan.client_id).where(ApplicationPlan.id == plan.id)
        )
        == target
    )
    db_session.execute(delete(Client).where(Client.id == target))
    db_session.commit()
    assert (
        db_session.scalar(
            select(ApplicationPlan.id).where(ApplicationPlan.id == plan.id)
        )
        is None
    )


def test_advisor_reads_only_its_own_manual_applications(require_db):
    from app.agent.tools import get_my_applications
    from app.deps import COOKIE_NAME

    owner, stranger = TestClient(app), TestClient(app)
    owner.post(
        "/api/application-records", json={"school": "Own Example", "name": "My MSc"}
    )
    stranger.get("/api/application-records")
    owned = get_my_applications.invoke(
        {}, config={"configurable": {"client_id": owner.cookies[COOKIE_NAME]}}
    )
    other = get_my_applications.invoke(
        {}, config={"configurable": {"client_id": stranger.cookies[COOKIE_NAME]}}
    )
    assert "Own Example" in owned
    assert "Own Example" not in other
