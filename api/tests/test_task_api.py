"""The per-row edit: the applicant's own door onto one task.

`PUT /api/roadmap/tasks` is the recomputation's door and may only ever touch the rows the client
generated; this module covers the other one, `PATCH /api/roadmap/tasks/{task_id}`. Three facts are
asserted here and none of them is visible from the write alone:

- the edit claims the row for the applicant, which is what makes the next recomputation leave the row
  alone;
- an edit aimed at another subject's row is a miss, and the test proves the *cookie* was read rather
  than merely that two clients differ: the same request succeeds on the caller's own row, the foreign
  row is asserted to still exist under the other subject, and only then is it a 404;
- the completion time travels with the status, so the interface never has to infer when something was
  finished from the fact that it is finished.

The rows are built through the recomputation route rather than inserted by hand, because that is how
the frontend creates them; the one exception is the advisor-owned row, which no client route can
write and which is therefore inserted directly.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.deps import COOKIE_NAME
from app.main import app
from app.models.task import RoadmapTask, TaskEvent, TaskOrigin, TaskStatus
from app.seed_roadmap import seed_roadmap

MATERIAL = "aca-transcript"
OTHER_MATERIAL = "aca-scale"
PHASE = "academic"


@pytest.fixture(autouse=True)
def remove_the_roadmap_definition_these_tests_seed(
    clear_the_roadmap_definition_after_the_test,
):
    """Delete the definition these tests seed again, the way the other seeding module does.

    ``seed_roadmap`` commits, and the ``db_session`` fixture's teardown only rolls back, so without
    this the phases, materials and the Genuine Student source stay in the shared development database
    for the rest of the run. The definition has to be empty when ``test_task_model.py`` and
    ``test_sources.py`` are collected — the session-scoped fixture in ``tests/conftest.py`` clears it
    before the first test for exactly that reason — and this module is collected between them, so it
    has to sweep what it seeds. The sweep itself lives in ``tests.conftest`` as a non-autouse fixture
    because as an autouse fixture there it would also run for ``test_roadmap_model.py`` and delete the
    rows that module asserts on.
    """


def _write_one_row(client: TestClient, material_key: str = MATERIAL, **wire_dates) -> dict:
    """Create one row through the recomputation route and return it as the read serves it."""
    written = client.put(
        "/api/roadmap/tasks",
        json={
            "applicableKeys": [material_key],
            "rows": [{"materialKey": material_key, "phase": PHASE, **wire_dates}],
        },
    )
    assert written.status_code == 200, written.text
    task = _row(client, None, material_key=material_key)
    assert task is not None, "the row the write created was not the row the read returns"
    return task


def _row(client: TestClient, task_id: str | None, material_key: str | None = None) -> dict | None:
    """One task as `GET /api/roadmap` serves it, by id or by material key."""
    for task in client.get("/api/roadmap").json()["tasks"]:
        if task_id is not None and task["id"] == task_id:
            return task
        if material_key is not None and task["materialKey"] == material_key:
            return task
    return None


def _events(session, task_id: str) -> list[TaskEvent]:
    """The history rows written for one task, read after expiring what this session already cached."""
    session.expire_all()
    return list(session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id)))


def _seconds_from_now(moment: datetime) -> float:
    """How far a stored instant is from now, so a fixed date cannot pass as a stamp."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return abs((datetime.now(timezone.utc) - moment).total_seconds())


def test_a_user_edit_flips_the_origin_and_records_history(require_db, db_session):
    """After this, a recompute must leave the row alone."""
    seed_roadmap(db_session)
    client = TestClient(app)
    task = _write_one_row(client)
    assert task["origin"] == TaskOrigin.SYSTEM

    edited = client.patch(
        f"/api/roadmap/tasks/{task['id']}", json={"status": TaskStatus.IN_PROGRESS.value}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["origin"] == TaskOrigin.USER, "the applicant's own edit did not claim the row"
    assert edited.json()["status"] == TaskStatus.IN_PROGRESS.value
    assert _row(client, task["id"])["origin"] == TaskOrigin.USER, (
        "the read did not serve the origin the write returned"
    )

    # What the flip buys. An empty applicable list is the caller stating that nothing is applicable
    # this round; while the row was `system` that statement would have removed it, and now it is kept.
    recompute = client.put("/api/roadmap/tasks", json={"applicableKeys": [], "rows": []})
    assert recompute.status_code == 200, recompute.text
    assert recompute.json() == {"created": 0, "updated": 0, "removed": 0, "kept": 1}
    assert _row(client, task["id"]) is not None, "a recomputation took back the row the applicant owns"

    events = _events(db_session, task["id"])
    assert len(events) == 2, "the creation and the edit are both in the history"
    assert {event.actor for event in events} == {TaskOrigin.SYSTEM, TaskOrigin.USER}
    edit = next(event for event in events if event.actor == TaskOrigin.USER)
    assert edit.event == "status_changed"
    assert edit.before["status"] == TaskStatus.PENDING and edit.before["origin"] == TaskOrigin.SYSTEM
    assert edit.after["status"] == TaskStatus.IN_PROGRESS and edit.after["origin"] == TaskOrigin.USER


def test_a_second_subject_cannot_edit_the_first_ones_task(require_db, db_session):
    """Cross-subject writes must be refused, and the test must prove the cookie was read: send the
    OTHER subject's task id under this subject's cookie and assert 404, not 200.
    """
    seed_roadmap(db_session)
    owner, stranger = TestClient(app), TestClient(app)
    owners_task = _write_one_row(owner, MATERIAL)
    strangers_task = _write_one_row(stranger, OTHER_MATERIAL)

    assert owner.cookies[COOKIE_NAME] != stranger.cookies[COOKIE_NAME], (
        "the two clients have to be different subjects for this test to mean anything"
    )

    # The control, and the half the earlier isolation test was missing: the same request, on the row
    # this cookie addresses, succeeds. A route that refused every edit would satisfy the 404 below.
    accepted = stranger.patch(
        f"/api/roadmap/tasks/{strangers_task['id']}", json={"status": TaskStatus.COMPLETED.value}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == TaskStatus.COMPLETED.value

    # The claim: the owner's task id, presented under the stranger's cookie, is a miss.
    refused = stranger.patch(
        f"/api/roadmap/tasks/{owners_task['id']}", json={"status": TaskStatus.COMPLETED.value}
    )
    assert refused.status_code == 404, (
        f"another subject's row was editable through this cookie: {refused.text}"
    )

    # The row existed and is untouched, which is what makes the 404 the subject filter talking rather
    # than a row that was not there to begin with.
    foreign = db_session.get(RoadmapTask, owners_task["id"])
    assert foreign is not None, "the refused edit removed the other subject's row"
    assert foreign.client_id == owner.cookies[COOKIE_NAME]
    assert foreign.status == TaskStatus.PENDING and foreign.origin == TaskOrigin.SYSTEM
    assert _row(owner, owners_task["id"])["status"] == TaskStatus.PENDING
    user_events = [
        event for event in _events(db_session, owners_task["id"]) if event.actor == TaskOrigin.USER
    ]
    assert not user_events, "the refused edit left a user event on the other subject's row"


def test_ticking_a_task_stamps_completed_at(require_db, db_session):
    seed_roadmap(db_session)
    client = TestClient(app)
    task = _write_one_row(client)
    assert task["completedAt"] is None, "a pending row has no completion time"

    edited = client.patch(f"/api/roadmap/tasks/{task['id']}", json={"status": TaskStatus.COMPLETED.value})
    assert edited.status_code == 200, edited.text
    served = edited.json()["completedAt"]
    assert served is not None, "ticking a task did not record when it was finished"

    stamp = datetime.fromisoformat(served)
    assert _seconds_from_now(stamp) < 300, (
        "the completion time is not the moment of the edit; a fixed date would pass 'is not None'"
    )
    row = db_session.get(RoadmapTask, task["id"])
    assert row is not None and row.completed_at is not None
    assert _seconds_from_now(row.completed_at) < 300


def test_unticking_clears_completed_at(require_db, db_session):
    seed_roadmap(db_session)
    client = TestClient(app)
    task = _write_one_row(client)

    ticked = client.patch(f"/api/roadmap/tasks/{task['id']}", json={"status": TaskStatus.COMPLETED.value})
    assert ticked.status_code == 200, ticked.text
    assert ticked.json()["completedAt"] is not None

    unticked = client.patch(
        f"/api/roadmap/tasks/{task['id']}", json={"status": TaskStatus.IN_PROGRESS.value}
    )
    assert unticked.status_code == 200, unticked.text
    assert unticked.json()["status"] == TaskStatus.IN_PROGRESS.value
    assert unticked.json()["completedAt"] is None, "leaving completed kept the completion time"

    row = db_session.get(RoadmapTask, task["id"])
    assert row is not None and row.completed_at is None


def test_an_unknown_task_id_is_404_not_a_silent_no_op(require_db, db_session):
    seed_roadmap(db_session)
    client = TestClient(app)
    task = _write_one_row(client)
    unknown = str(uuid.uuid4())

    # The control: the route addresses this subject's own rows, so the same request on the row the
    # cookie names succeeds. Without it this test would also pass on a route that was never written,
    # which is exactly how the 404 it asserts could stop meaning anything.
    accepted = client.patch(
        f"/api/roadmap/tasks/{task['id']}", json={"status": TaskStatus.IN_PROGRESS.value}
    )
    assert accepted.status_code == 200, accepted.text

    refused = client.patch(f"/api/roadmap/tasks/{unknown}", json={"status": TaskStatus.COMPLETED.value})
    assert refused.status_code == 404, refused.text

    assert not _events(db_session, unknown), "a miss wrote history for a row that does not exist"
    served = client.get("/api/roadmap").json()["tasks"]
    assert [row["id"] for row in served] == [task["id"]], "a miss invented or removed a row"
    assert served[0]["status"] == TaskStatus.IN_PROGRESS.value, "a miss moved the row it never found"
    assert served[0]["origin"] == TaskOrigin.USER


def test_an_advisor_owned_row_keeps_its_origin(require_db, db_session):
    """The advisor still owns the row's provenance after the applicant changes its status.

    No client route writes an `agent` row, so this one is inserted directly. The edit is expected to
    succeed and to move the status — and to leave `origin` where the advisor put it.
    """
    seed_roadmap(db_session)
    client = TestClient(app)
    client.get("/api/profile")
    task_id = str(uuid.uuid4())
    db_session.add(
        RoadmapTask(
            id=task_id,
            client_id=client.cookies[COOKIE_NAME],
            material_key=MATERIAL,
            program_id="",
            phase=PHASE,
            origin=TaskOrigin.AGENT,
        )
    )
    db_session.commit()

    edited = client.patch(f"/api/roadmap/tasks/{task_id}", json={"status": TaskStatus.COMPLETED.value})
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == TaskStatus.COMPLETED.value
    assert edited.json()["origin"] == TaskOrigin.AGENT, (
        "the applicant took over the advisor's row by editing its status"
    )

    db_session.expire_all()
    row = db_session.get(RoadmapTask, task_id)
    assert row is not None and row.origin == TaskOrigin.AGENT
    assert [event.actor for event in _events(db_session, task_id)] == [TaskOrigin.USER]


def test_a_patch_cannot_claim_an_origin(require_db, db_session):
    """`TaskIn` refuses `origin` so a recomputation cannot claim ownership; the patch must too.

    `materialKey` and `phase` are refused for the neighbouring reason: a row's identity and its place
    in the timeline are the recomputation's and the definition's, and a per-row edit is the status and
    the dates. A payload sending any of them has misunderstood the route, so it is a 422 naming the
    field rather than a value silently dropped.

    Every body below states a legal field **as well as** the refused one, and that is what makes the
    test able to fail. Built as one forbidden key per body it could not: under `extra="ignore"` the
    body then states nothing at all, the "a patch must state something" validator refuses it, and the
    422 arrives for a reason that has nothing to do with the field this test is about — measured by
    switching `TaskPatch`'s `extra` to `"ignore"` and watching both this test and its sibling pass.
    With `status` in the body the distinction is real: `ignore` drops the forbidden key, the edit is
    applied, the row's status moves and its `origin` flips to `user` — the exact claim of provenance
    the batch rests on — so the assertions after the loop fail. The refusal is also checked to name
    the field, because a 422 that says only "invalid body" would leave "silently dropped" and
    "refused" indistinguishable to the applicant.
    """
    seed_roadmap(db_session)
    client = TestClient(app)
    task = _write_one_row(client)

    for field, body in (
        ("origin", {"status": TaskStatus.IN_PROGRESS.value, "origin": "user"}),
        ("materialKey", {"status": TaskStatus.IN_PROGRESS.value, "materialKey": OTHER_MATERIAL}),
        ("phase", {"status": TaskStatus.IN_PROGRESS.value, "phase": "visa"}),
        ("scheduleOrigin", {"status": TaskStatus.IN_PROGRESS.value, "scheduleOrigin": "official"}),
    ):
        refused = client.patch(f"/api/roadmap/tasks/{task['id']}", json=body)
        assert refused.status_code == 422, f"{body} was accepted: {refused.text}"
        assert field in refused.text, f"the refusal did not name {field}: {refused.text}"

    served = _row(client, task["id"])
    assert served["origin"] == TaskOrigin.SYSTEM, "a refused patch claimed the row for the user"
    assert served["materialKey"] == MATERIAL and served["phase"] == PHASE
    # The half a 422 alone does not prove: the legal field these bodies carried never landed either.
    # A route that refused the unknown key and applied the rest would leave the row edited, and the
    # applicant's mark — which freezes the row against every later recomputation — would be there
    # without the edit they thought they were making.
    assert served["status"] == TaskStatus.PENDING, "a refused patch applied the fields around it"
    assert not [event for event in _events(db_session, task["id"]) if event.actor == TaskOrigin.USER]


def test_a_patch_that_names_no_field_is_refused(require_db, db_session):
    """An empty patch is not an edit, so it must not be read as one.

    Accepting it would have a side effect with no instruction behind it: every accepted edit claims
    the row for the applicant, and a claimed row is one no recomputation may touch again. A caller
    that sent `{}` — a bug, or a form that submitted nothing — would freeze the row against the
    recomputation that keeps its dates current. `status: null` is refused with it, because a status is
    not something that can be cleared: the other two fields are nullable columns and a null there is a
    real statement.
    """
    seed_roadmap(db_session)
    client = TestClient(app)
    task = _write_one_row(client)

    for body in ({}, {"status": None}):
        refused = client.patch(f"/api/roadmap/tasks/{task['id']}", json=body)
        assert refused.status_code == 422, f"{body} was accepted: {refused.text}"

    served = _row(client, task["id"])
    assert served["origin"] == TaskOrigin.SYSTEM, "a refused patch claimed the row for the user"
    assert served["status"] == TaskStatus.PENDING
    assert not [event for event in _events(db_session, task["id"]) if event.actor == TaskOrigin.USER]


def test_a_date_the_patch_omits_survives_and_a_null_clears_it(require_db, db_session):
    """The rule `TaskIn` states for a recomputation holds for the applicant's edit as well.

    A field the payload does not carry leaves the row's date alone; an explicit null says the row has
    no date. Without the distinction, editing the suggestion date would silently wipe a deadline the
    row held — a loss the caller cannot see in its own payload.
    """
    seed_roadmap(db_session)
    client = TestClient(app)
    task = _write_one_row(client, suggestedAt="2027-06-01", dueAt="2027-07-01")
    assert (task["suggestedAt"], task["dueAt"]) == ("2027-06-01", "2027-07-01")

    moved = client.patch(f"/api/roadmap/tasks/{task['id']}", json={"suggestedAt": "2027-06-15"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["suggestedAt"] == "2027-06-15"
    assert moved.json()["dueAt"] == "2027-07-01", "a date the patch did not mention was wiped"

    cleared = client.patch(f"/api/roadmap/tasks/{task['id']}", json={"dueAt": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["dueAt"] is None
    assert cleared.json()["suggestedAt"] == "2027-06-15", "clearing one date cleared the other"
