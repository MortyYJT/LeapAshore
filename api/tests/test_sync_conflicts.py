"""Two devices of one account: a stale update is refused, and a retried create writes one row.

Every applicant-editable record carries a version, and an update states the version it was based on
(`docs/product/PRD-multi-device.md`, 3.3). The tests here run two devices of one subject against the
same record:

- sequentially, where the second device still holds the version the first one already replaced;
- at the same moment, released together by a barrier, where the server must accept exactly one.

The concurrent rounds pass only when the version is compared and the row written under one lock:
without it both requests read the same version and both are accepted.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.deps import COOKIE_NAME
from app.main import app
from app.models.application_plan import ApplicationPlan
from app.seed import seed_programs
from app.seed_roadmap import seed_roadmap
from tests.test_seed import PROGRAM_IDS

RECORDS = "/api/application-records"
ROUNDS = 10
MATERIAL = "aca-transcript"


def second_device(first: TestClient) -> TestClient:
    """Another client of the same subject: its own connection, the same cookie."""
    other = TestClient(app)
    other.cookies.set(COOKIE_NAME, first.cookies[COOKIE_NAME])
    return other


def at_once(*calls: Callable):
    """Run the calls on their own threads, released together, and return their results in order."""
    barrier = threading.Barrier(len(calls))

    def run(call):
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [future.result(timeout=30) for future in futures]


def new_key() -> str:
    return str(uuid.uuid4())


def create_record(client: TestClient, key: str | None = None, **fields):
    body = {"school": "Example University", "name": "Example MSc", **fields}
    return client.post(RECORDS, json=body, headers={"Idempotency-Key": key or new_key()})


def one_winner(responses, what: str):
    """Exactly one 200 and one 409, returned as (winner, loser)."""
    codes = sorted(response.status_code for response in responses)
    assert codes == [200, 409], f"{what}: expected one accepted and one refused, got {codes}"
    winner = next(r for r in responses if r.status_code == 200)
    loser = next(r for r in responses if r.status_code == 409)
    return winner, loser


# --- application records -------------------------------------------------------------------------


def test_a_stale_update_to_an_application_record_is_refused_with_the_server_state(require_db):
    phone = TestClient(app)
    record = create_record(phone).json()
    laptop = second_device(phone)

    first = phone.patch(
        f"{RECORDS}/{record['id']}", json={"round": "Round 1", "baseVersion": record["version"]}
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] != record["version"], "an accepted update must move the version"

    stale = laptop.patch(
        f"{RECORDS}/{record['id']}",
        json={"materialNotes": "written on the laptop", "baseVersion": record["version"]},
    )
    assert stale.status_code == 409, stale.text
    body = stale.json()
    assert body["code"] == "stale_version"
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["current"] == first.json(), "the refusal must carry the record as the server holds it"

    stored = phone.get(RECORDS).json()[0]
    assert stored["round"] == "Round 1" and stored["materialNotes"] == ""

    # Keeping the laptop's edit is the same update, restated on the version the refusal returned.
    kept = laptop.patch(
        f"{RECORDS}/{record['id']}",
        json={"materialNotes": "written on the laptop", "baseVersion": body["current"]["version"]},
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["round"] == "Round 1"
    assert kept.json()["materialNotes"] == "written on the laptop"


def test_an_update_without_a_base_version_is_rejected(require_db):
    client = TestClient(app)
    record = create_record(client).json()
    assert client.patch(f"{RECORDS}/{record['id']}", json={"round": "R1"}).status_code == 422
    assert client.delete(f"{RECORDS}/{record['id']}").status_code == 422


def test_two_concurrent_updates_to_one_application_record_accept_exactly_one(require_db):
    phone = TestClient(app)
    record = create_record(phone).json()
    laptop = second_device(phone)

    for round_no in range(ROUNDS):
        base = phone.get(RECORDS).json()[0]
        notes = {"phone": f"phone {round_no}", "laptop": f"laptop {round_no}"}
        responses = at_once(
            lambda: phone.patch(
                f"{RECORDS}/{record['id']}",
                json={"materialNotes": notes["phone"], "baseVersion": base["version"]},
            ),
            lambda: laptop.patch(
                f"{RECORDS}/{record['id']}",
                json={"materialNotes": notes["laptop"], "baseVersion": base["version"]},
            ),
        )
        winner, loser = one_winner(responses, f"round {round_no}")
        stored = phone.get(RECORDS).json()[0]
        assert stored == winner.json(), "the stored record is the accepted update"
        assert loser.json()["current"] == stored, "the refused device is told what was stored"
        assert stored["materialNotes"] in notes.values()


def test_a_stale_update_to_a_catalogue_record_is_refused_whichever_row_moved(require_db, db_session):
    """A catalogue record is a portfolio row plus an optional overlay; a change to either is a change."""
    seed_programs(db_session)
    phone = TestClient(app)
    program = PROGRAM_IDS[0]
    assert phone.put(
        "/api/applications", json={"rows": [{"programId": program, "tier": "稳"}]}
    ).status_code == 200
    laptop = second_device(phone)
    record = laptop.get(RECORDS).json()[0]

    # The overlay does not exist yet; the first edit creates it and still moves the version.
    edited = phone.patch(
        f"{RECORDS}/{record['id']}", json={"round": "R1", "baseVersion": record["version"]}
    )
    assert edited.status_code == 200, edited.text
    stale = laptop.patch(
        f"{RECORDS}/{record['id']}", json={"status": "submitted", "baseVersion": record["version"]}
    )
    assert stale.status_code == 409 and stale.json()["current"] == edited.json()

    # The portfolio page changes the same program's status through the other route.
    held = edited.json()
    rows = phone.get("/api/applications").json()
    moved = phone.put(
        "/api/applications",
        json={
            "rows": [{"programId": program, "tier": "稳", "status": "applying"}],
            "base": [{"id": row["id"], "version": row["version"]} for row in rows],
        },
    )
    assert moved.status_code == 200, moved.text
    stale = laptop.patch(
        f"{RECORDS}/{record['id']}", json={"round": "R2", "baseVersion": held["version"]}
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["current"]["status"] == "applying"
    assert stale.json()["current"]["round"] == "R1"


def test_removing_a_record_states_its_version_too(require_db):
    phone = TestClient(app)
    record = create_record(phone).json()
    laptop = second_device(phone)
    edited = phone.patch(
        f"{RECORDS}/{record['id']}", json={"round": "R1", "baseVersion": record["version"]}
    ).json()

    stale = laptop.delete(f"{RECORDS}/{record['id']}", params={"baseVersion": record["version"]})
    assert stale.status_code == 409 and stale.json()["current"] == edited
    assert len(phone.get(RECORDS).json()) == 1, "a refused removal removed the record"

    removed = laptop.delete(f"{RECORDS}/{record['id']}", params={"baseVersion": edited["version"]})
    assert removed.status_code == 204
    assert phone.get(RECORDS).json() == []


# --- idempotent create ---------------------------------------------------------------------------


def plans_of(client: TestClient) -> int:
    with SessionLocal() as session:
        return session.scalar(
            select(func.count())
            .select_from(ApplicationPlan)
            .where(ApplicationPlan.client_id == client.cookies[COOKIE_NAME])
        )


def test_a_retried_create_returns_the_first_record_and_writes_one_row(require_db):
    client = TestClient(app)
    key = new_key()
    first = create_record(client, key, round="Round 1")
    assert first.status_code == 201, first.text

    retried = create_record(client, key, round="Round 1")
    assert retried.status_code == 200, "a replay answers 200, a creation 201"
    assert retried.json() == first.json()
    assert plans_of(client) == 1
    assert len(client.get(RECORDS).json()) == 1

    # A replay never writes: an edit made after the creation survives a late duplicate of the create.
    edited = client.patch(
        f"{RECORDS}/{first.json()['id']}",
        json={"round": "Round 2", "baseVersion": first.json()["version"]},
    ).json()
    late = create_record(client, key, round="Round 1")
    assert late.status_code == 200 and late.json() == edited

    other = create_record(client, new_key())
    assert other.status_code == 201 and other.json()["id"] != first.json()["id"]
    assert plans_of(client) == 2


def test_a_create_retried_at_the_same_moment_writes_one_row(require_db):
    phone = TestClient(app)
    phone.get("/api/profile")
    laptop = second_device(phone)

    for round_no in range(ROUNDS):
        key = new_key()
        responses = at_once(
            lambda: create_record(phone, key, name=f"MSc {round_no}"),
            lambda: create_record(laptop, key, name=f"MSc {round_no}"),
        )
        codes = sorted(response.status_code for response in responses)
        assert codes == [200, 201], f"round {round_no}: {codes}"
        assert responses[0].json()["id"] == responses[1].json()["id"]
        assert plans_of(phone) == round_no + 1


def test_a_create_needs_an_idempotency_key_and_keys_are_per_subject(require_db):
    owner, stranger = TestClient(app), TestClient(app)
    body = {"school": "Example University", "name": "Example MSc"}
    assert owner.post(RECORDS, json=body).status_code == 422
    assert owner.post(RECORDS, json=body, headers={"Idempotency-Key": "x"}).status_code == 422
    assert plans_of_or_zero(owner) == 0

    key = new_key()
    mine = create_record(owner, key)
    theirs = create_record(stranger, key)
    assert mine.status_code == 201 and theirs.status_code == 201
    assert mine.json()["id"] != theirs.json()["id"], "one subject's key must not answer for another's"


def plans_of_or_zero(client: TestClient) -> int:
    return plans_of(client) if COOKIE_NAME in client.cookies else 0


# --- the portfolio -------------------------------------------------------------------------------


def base_of(rows: list[dict]) -> list[dict]:
    return [{"id": row["id"], "version": row["version"]} for row in rows]


def test_a_stale_portfolio_replacement_is_refused_with_the_server_rows(require_db, db_session):
    seed_programs(db_session)
    first, second, third = PROGRAM_IDS[:3]
    phone = TestClient(app)
    assert phone.put(
        "/api/applications", json={"rows": [{"programId": first, "tier": "稳"}]}
    ).status_code == 200
    laptop = second_device(phone)
    seen = laptop.get("/api/applications").json()

    added = phone.put(
        "/api/applications",
        json={
            "rows": [{"programId": first, "tier": "稳"}, {"programId": second, "tier": "冲"}],
            "base": base_of(seen),
        },
    )
    assert added.status_code == 200, added.text

    # The laptop's draft was made before the phone added a program: confirming it would remove it.
    stale = laptop.put(
        "/api/applications",
        json={
            "rows": [{"programId": first, "tier": "稳"}, {"programId": third, "tier": "保"}],
            "base": base_of(seen),
        },
    )
    assert stale.status_code == 409, stale.text
    current = stale.json()["current"]
    assert stale.json()["code"] == "stale_version"
    assert {row["programId"] for row in current} == {first, second}
    assert current == phone.get("/api/applications").json()

    # No base at all claims an empty portfolio, which is stale here as well.
    assert laptop.put("/api/applications", json={"rows": []}).status_code == 409
    assert len(phone.get("/api/applications").json()) == 2

    kept = laptop.put(
        "/api/applications",
        json={
            "rows": [{"programId": first, "tier": "稳"}, {"programId": third, "tier": "保"}],
            "base": base_of(current),
        },
    )
    assert kept.status_code == 200, kept.text
    assert {row["programId"] for row in phone.get("/api/applications").json()} == {first, third}


def test_two_concurrent_portfolio_replacements_accept_exactly_one(require_db, db_session):
    seed_programs(db_session)
    first, second, third = PROGRAM_IDS[:3]
    phone = TestClient(app)
    assert phone.put(
        "/api/applications", json={"rows": [{"programId": first, "tier": "稳"}]}
    ).status_code == 200
    laptop = second_device(phone)

    for round_no in range(ROUNDS):
        seen = phone.get("/api/applications").json()
        # Each device adds or drops its own program, so the two payloads always differ from the
        # stored portfolio and from each other.
        held = {row["programId"] for row in seen}
        mine, theirs = sorted(held ^ {second}), sorted(held ^ {third})
        responses = at_once(
            lambda: phone.put(
                "/api/applications",
                json={"rows": [{"programId": p, "tier": "稳"} for p in mine], "base": base_of(seen)},
            ),
            lambda: laptop.put(
                "/api/applications",
                json={"rows": [{"programId": p, "tier": "稳"} for p in theirs], "base": base_of(seen)},
            ),
        )
        winner, loser = one_winner(responses, f"round {round_no}")
        stored = phone.get("/api/applications").json()
        won = mine if winner is responses[0] else theirs
        assert {row["programId"] for row in stored} == set(won)
        assert loser.json()["current"] == stored


# --- roadmap tasks -------------------------------------------------------------------------------


@pytest.fixture
def seeded_roadmap(db_session, clear_the_roadmap_definition_after_the_test):
    seed_roadmap(db_session)


def task_of(client: TestClient) -> dict:
    written = client.put(
        "/api/roadmap/tasks",
        json={"applicableKeys": [MATERIAL], "rows": [{"materialKey": MATERIAL, "phase": "academic"}]},
    )
    assert written.status_code == 200, written.text
    return read_task(client)


def read_task(client: TestClient) -> dict:
    return next(t for t in client.get("/api/roadmap").json()["tasks"] if t["materialKey"] == MATERIAL)


def test_a_stale_task_update_is_refused_with_the_server_row(require_db, seeded_roadmap):
    phone = TestClient(app)
    task = task_of(phone)
    assert task["version"] == 1
    laptop = second_device(phone)

    done = phone.patch(
        f"/api/roadmap/tasks/{task['id']}",
        json={"status": "completed", "baseVersion": task["version"]},
    )
    assert done.status_code == 200 and done.json()["version"] == 2

    stale = laptop.patch(
        f"/api/roadmap/tasks/{task['id']}",
        json={"status": "skipped", "baseVersion": task["version"]},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_version"
    assert stale.json()["current"] == done.json()
    assert read_task(phone)["status"] == "completed"

    assert phone.patch(
        f"/api/roadmap/tasks/{task['id']}", json={"status": "pending"}
    ).status_code == 422, "an edit that does not state its base version is not accepted"

    kept = laptop.patch(
        f"/api/roadmap/tasks/{task['id']}", json={"status": "skipped", "baseVersion": 2}
    )
    assert kept.status_code == 200 and kept.json()["version"] == 3


def test_a_recomputation_moves_the_version_of_the_rows_it_rewrites(require_db, seeded_roadmap):
    """Whoever changes a row moves its version, so a device holding the old dates is told."""
    client = TestClient(app)
    task = task_of(client)
    again = client.put(
        "/api/roadmap/tasks",
        json={
            "applicableKeys": [MATERIAL],
            "rows": [{"materialKey": MATERIAL, "phase": "academic", "dueAt": "2027-03-01"}],
        },
    )
    assert again.status_code == 200
    assert read_task(client)["version"] == task["version"] + 1
    # Restating the same rows changes nothing, so the version stays.
    client.put(
        "/api/roadmap/tasks",
        json={
            "applicableKeys": [MATERIAL],
            "rows": [{"materialKey": MATERIAL, "phase": "academic", "dueAt": "2027-03-01"}],
        },
    )
    assert read_task(client)["version"] == task["version"] + 1


def test_two_concurrent_updates_to_one_task_accept_exactly_one(require_db, seeded_roadmap):
    phone = TestClient(app)
    task = task_of(phone)
    laptop = second_device(phone)
    url = f"/api/roadmap/tasks/{task['id']}"

    for round_no in range(ROUNDS):
        base = read_task(phone)
        # Two values that both differ from the stored one, so each request is a real change.
        choices = [s for s in ("completed", "skipped", "in_progress") if s != base["status"]]
        responses = at_once(
            lambda: phone.patch(url, json={"status": choices[0], "baseVersion": base["version"]}),
            lambda: laptop.patch(url, json={"status": choices[1], "baseVersion": base["version"]}),
        )
        winner, loser = one_winner(responses, f"round {round_no}")
        stored = read_task(phone)
        assert stored == winner.json()
        assert stored["version"] == base["version"] + 1, "one accepted update is one version step"
        assert loser.json()["current"] == stored


# --- the profile ---------------------------------------------------------------------------------


def test_a_stale_profile_update_is_refused_with_the_server_profile(require_db):
    phone = TestClient(app)
    profile = phone.get("/api/profile").json()
    assert profile["version"] == 1
    laptop = second_device(phone)

    saved = phone.patch("/api/profile", json={"major": "计算机科学", "baseVersion": 1})
    assert saved.status_code == 200 and saved.json()["version"] == 2

    stale = laptop.patch("/api/profile", json={"intake": "2027 S2", "baseVersion": 1})
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_version"
    assert stale.json()["current"] == saved.json()
    assert phone.get("/api/profile").json()["intake"] is None

    assert phone.patch("/api/profile", json={"intake": "2027 S2"}).status_code == 422

    kept = laptop.patch("/api/profile", json={"intake": "2027 S2", "baseVersion": 2})
    assert kept.status_code == 200
    assert kept.json()["major"] == "计算机科学" and kept.json()["intake"] == "2027 S2"
    assert kept.json()["version"] == 3


def test_two_concurrent_profile_updates_accept_exactly_one(require_db):
    phone = TestClient(app)
    phone.get("/api/profile")
    laptop = second_device(phone)

    for round_no in range(ROUNDS):
        base = phone.get("/api/profile").json()
        responses = at_once(
            lambda: phone.patch(
                "/api/profile", json={"major": f"phone {round_no}", "baseVersion": base["version"]}
            ),
            lambda: laptop.patch(
                "/api/profile", json={"major": f"laptop {round_no}", "baseVersion": base["version"]}
            ),
        )
        winner, loser = one_winner(responses, f"round {round_no}")
        stored = phone.get("/api/profile").json()
        assert stored == winner.json()
        assert stored["version"] == base["version"] + 1
        assert loser.json()["current"] == stored
