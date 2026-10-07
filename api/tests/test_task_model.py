import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.client import Client
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.task import RoadmapTask, TaskEvent, TaskOrigin

PROBE_PHASE = "probe-phase"
PROBE_MATERIAL = "probe-mat"


@pytest.fixture(autouse=True)
def remove_the_probe_definition_these_tests_write():
    """Delete the probe phase and material this module adds, so the shared database is left as found.

    ``conftest``'s autouse fixture sweeps the *subjects* a test creates, and the session-scoped one
    restores the roadmap definition afterwards. Neither removes configuration rows the tests
    committed: the session fixture's teardown only calls ``seed_roadmap``, which inserts the
    canonical phases and materials and never deletes a row the tests wrote. A stray
    ``probe-mat``/``probe-phase`` pair would therefore survive a run, and the next session's setup
    would have to clean up after it. ``test_roadmap_model.py`` deletes what it writes for the same
    reason; this is the module-scoped version, because every test here shares the one pair.

    The order matters: ``material_templates.phase`` is RESTRICT, so the material has to go before the
    phase that owns it.
    """
    yield
    with SessionLocal() as session:
        session.execute(delete(MaterialTemplate).where(MaterialTemplate.key == PROBE_MATERIAL))
        session.execute(delete(RoadmapPhase).where(RoadmapPhase.key == PROBE_PHASE))
        session.commit()


def _subject(db_session):
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.flush()
    return client_id


def _material(db_session, key=PROBE_MATERIAL):
    if db_session.get(RoadmapPhase, PROBE_PHASE) is None:
        db_session.add(RoadmapPhase(key=PROBE_PHASE, title="探测", offset_days=10, sort_order=99))
        db_session.flush()
    if db_session.get(MaterialTemplate, key) is None:
        db_session.add(
            MaterialTemplate(key=key, phase=PROBE_PHASE, title="探测材料", applies_to="all")
        )
        db_session.flush()
    return key


def test_task_defaults_to_a_system_row(db_session, require_db):
    """A row the client computed must never be mistaken for one a human or the advisor owns."""
    client_id = _subject(db_session)
    _material(db_session)
    db_session.add(
        RoadmapTask(
            id=str(uuid.uuid4()),
            client_id=client_id,
            material_key=PROBE_MATERIAL,
            program_id="",
            phase=PROBE_PHASE,
        )
    )
    db_session.commit()

    row = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalar_one()
    assert row.origin == TaskOrigin.SYSTEM
    assert row.status == "pending"
    # An unfilled date must read as unknown, not as a default the applicant never chose.
    assert row.due_at is None

    db_session.delete(row)
    db_session.commit()


def test_one_row_per_subject_material_and_program(db_session, require_db):
    client_id = _subject(db_session)
    _material(db_session)
    for _ in range(2):
        db_session.add(
            RoadmapTask(
                id=str(uuid.uuid4()),
                client_id=client_id,
                material_key=PROBE_MATERIAL,
                program_id="",
                phase=PROBE_PHASE,
            )
        )
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("a duplicate (client, material, program) row was accepted")
    finally:
        for row in db_session.execute(
            select(RoadmapTask).where(RoadmapTask.client_id == client_id)
        ).scalars():
            db_session.delete(row)
        db_session.commit()


def test_deleting_a_subject_removes_its_tasks_and_events(db_session, require_db):
    """The empty string is not the only reason `client_id` is a foreign key: it is also the sweep.

    Deleting a subject has to take everything it owns with it, or the development database fills up
    with rows nothing points at. `task_id` is deliberately left out of that sweep, which is what the
    next test pins down.
    """
    client_id = _subject(db_session)
    _material(db_session)
    task_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    db_session.add(
        RoadmapTask(
            id=task_id,
            client_id=client_id,
            material_key=PROBE_MATERIAL,
            program_id="",
            phase=PROBE_PHASE,
        )
    )
    db_session.add(
        TaskEvent(id=event_id, client_id=client_id, task_id=task_id, actor="user", event="created")
    )
    db_session.commit()

    db_session.delete(db_session.get(Client, client_id))
    db_session.commit()

    assert db_session.get(RoadmapTask, task_id) is None, "the task outlived its subject"
    assert db_session.get(TaskEvent, event_id) is None, "the event outlived its subject"


def test_event_survives_its_task_being_deleted(db_session, require_db):
    """A history entry must outlive the row it describes, or the audit trail has holes."""
    client_id = _subject(db_session)
    _material(db_session)
    task_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    db_session.add(
        RoadmapTask(
            id=task_id,
            client_id=client_id,
            material_key=PROBE_MATERIAL,
            program_id="",
            phase=PROBE_PHASE,
        )
    )
    db_session.add(
        TaskEvent(id=event_id, client_id=client_id, task_id=task_id, actor="user", event="created")
    )
    db_session.commit()

    db_session.delete(db_session.get(RoadmapTask, task_id))
    db_session.commit()

    kept = db_session.get(TaskEvent, event_id)
    assert kept is not None, "the event vanished with its task"
    assert kept.task_id == task_id

    db_session.delete(kept)
    db_session.delete(db_session.get(Client, client_id))
    db_session.commit()
