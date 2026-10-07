import uuid
from datetime import date

from sqlalchemy import select

from app.models.client import Client
from app.models.task import RoadmapTask, TaskEvent, TaskOrigin
from app.seed_roadmap import seed_roadmap
from app.services.roadmap_tasks import replace_system_tasks


def _subject(db_session):
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.commit()
    return client_id


def _task(db_session, client_id, key, origin=TaskOrigin.SYSTEM, status="pending"):
    task = RoadmapTask(
        id=str(uuid.uuid4()),
        client_id=client_id,
        material_key=key,
        program_id="",
        phase="selection",
        status=status,
        origin=origin,
        suggested_at=date(2027, 1, 1),
    )
    db_session.add(task)
    db_session.commit()
    return task


KEYS = ["aca-transcript", "aca-id-photo"]


def test_writes_the_system_rows(db_session, require_db):
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    result = replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 1, 1)}],
    )
    assert result["created"] == 1

    rows = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalars().all()
    assert [r.material_key for r in rows] == ["aca-transcript"]
    assert rows[0].origin == TaskOrigin.SYSTEM


def test_a_recompute_never_touches_a_users_row(db_session, require_db):
    """The rule this batch exists for."""
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    _task(db_session, client_id, "aca-transcript", origin=TaskOrigin.USER, status="completed")

    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 6, 1)}],
    )

    kept = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalar_one()
    assert kept.origin == TaskOrigin.USER
    assert kept.status == "completed"
    assert kept.suggested_at == date(2027, 1, 1), "a recompute overwrote a row the user owns"


def test_a_recompute_never_touches_an_agent_row(db_session, require_db):
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    _task(db_session, client_id, "aca-transcript", origin=TaskOrigin.AGENT, status="in_progress")

    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 6, 1)}],
    )

    kept = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalar_one()
    assert kept.origin == TaskOrigin.AGENT
    assert kept.status == "in_progress"


def test_a_recompute_keeps_the_status_of_its_own_rows(db_session, require_db):
    """Ticking a box must survive a later recompute."""
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    _task(db_session, client_id, "aca-transcript", status="completed")

    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 6, 1)}],
    )

    kept = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalar_one()
    assert kept.status == "completed", "a recompute lost the applicant's completed mark"
    assert kept.suggested_at == date(2027, 6, 1), "a recompute must still update the dates it owns"


def test_rows_no_longer_applicable_are_removed_only_when_the_caller_says_so(db_session, require_db):
    """Absent from this payload and no longer applicable are different claims (design section 3.8)."""
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    _task(db_session, client_id, "aca-transcript")

    # The caller supplies only one of the two keys it says are applicable, and does not list the other
    # as applicable: the row it omits must stay, because "not mentioned" is not "removed".
    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=["aca-transcript"],
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 1, 1)}],
    )
    assert db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalars().all(), "an unmentioned row was deleted"

    # Now the caller says the key is genuinely no longer applicable: the row goes.
    replace_system_tasks(db_session, client_id, applicable_keys=[], rows=[])
    assert (
        db_session.execute(
            select(RoadmapTask).where(RoadmapTask.client_id == client_id)
        ).scalars().all()
        == []
    )


def test_every_replacement_writes_history(db_session, require_db):
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 1, 1)}],
    )
    events = db_session.execute(
        select(TaskEvent).where(TaskEvent.client_id == client_id)
    ).scalars().all()
    assert events, "a write left no history"
    assert all(e.actor == "system" for e in events)
