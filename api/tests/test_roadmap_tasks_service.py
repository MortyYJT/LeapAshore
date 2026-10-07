import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.models.client import Client
from app.models.task import RoadmapTask, TaskEvent, TaskOrigin
from app.seed_roadmap import seed_roadmap
from app.services.roadmap_tasks import InvalidTaskPayload, replace_system_tasks

# The six tests above are the brief's, copied verbatim. Everything below was added in the fix round
# for the review findings: the counts the service reports, the contradictory payload it now refuses,
# the partial update an omitted date means, and the reference checks that replaced the foreign key's
# 500. The brief's six are untouched.


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


def _state(db_session, client_id):
    """The rows one subject holds, as plain values, so two moments can be compared."""
    return sorted(
        (
            row.material_key,
            row.program_id,
            row.phase,
            row.status,
            row.suggested_at,
            row.due_at,
            row.schedule_origin,
            row.origin,
            row.completed_at,
        )
        for row in db_session.execute(
            select(RoadmapTask).where(RoadmapTask.client_id == client_id)
        ).scalars()
    )


def test_the_four_counts_are_disjoint_and_mean_what_they_say(db_session, require_db):
    """`kept` is what the call left alone, not `len(existing) - removed`.

    That arithmetic counted one rescheduled system row in both `updated` and `kept`, so a call that
    touched a single row reported having written it and having left it alone at the same time. This
    scenario is built to hit all four counts at once, and the four add up to the rows that existed:
    one row updated, one deleted because its key is no longer applicable, one user row the rule
    protects, and one system row the caller still calls applicable without sending a row for it.
    """
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    _task(db_session, client_id, "aca-transcript")
    _task(db_session, client_id, "aca-passport", origin=TaskOrigin.USER, status="completed")
    _task(db_session, client_id, "aca-scale")
    _task(db_session, client_id, "aca-enroll")

    result = replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=["aca-transcript", "aca-passport", "aca-scale"],
        rows=[
            {
                "material_key": "aca-transcript",
                "phase": "academic",
                "suggested_at": date(2027, 6, 1),
            }
        ],
    )

    assert result == {"created": 0, "updated": 1, "removed": 1, "kept": 2}, (
        "the counts must be disjoint: an updated row is not also a kept row"
    )
    rows = {row.material_key: row for row in db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalars()}
    assert sorted(rows) == ["aca-passport", "aca-scale", "aca-transcript"]
    assert rows["aca-transcript"].suggested_at == date(2027, 6, 1), "the row this call owns did not move"
    assert rows["aca-scale"].suggested_at == date(2027, 1, 1), "a row the caller only called applicable was written"
    assert rows["aca-passport"].status == "completed", "the user's row was touched"


def test_a_contradictory_payload_is_refused_before_anything_is_written(db_session, require_db):
    """A key in `rows` and not in `applicable_keys` is refused, not interpreted.

    Interpreting it both ways in one call is what made the same payload create a row and then delete
    it — or delete a row that was already there — depending on state the caller could not see. The
    refusal is raised before the first write, so a rejected payload leaves the roadmap untouched.
    """
    seed_roadmap(db_session)
    client_id = _subject(db_session)

    with pytest.raises(InvalidTaskPayload) as raised:
        replace_system_tasks(
            db_session,
            client_id,
            applicable_keys=[],
            rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 1, 1)}],
        )

    assert "aca-transcript" in str(raised.value), "the message must name the key that disagrees"
    assert _state(db_session, client_id) == [], "a rejected payload wrote a row"
    assert db_session.execute(
        select(TaskEvent).where(TaskEvent.client_id == client_id)
    ).scalars().all() == [], "a rejected payload left history"


def test_the_same_payload_twice_leaves_the_same_state(db_session, require_db):
    """Measured before the fix: call 1 left the row, call 2 emitted created + rescheduled + removed.

    The second call is not a no-op in either version — it re-states the dates it owns — but the rows
    it leaves behind have to be the same rows, which is what makes a retried recomputation safe.
    """
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    payload = [
        {
            "material_key": "aca-transcript",
            "phase": "academic",
            "suggested_at": date(2027, 1, 1),
            "due_at": date(2027, 2, 1),
        }
    ]

    first = replace_system_tasks(db_session, client_id, applicable_keys=KEYS, rows=payload)
    after_first = _state(db_session, client_id)
    second = replace_system_tasks(db_session, client_id, applicable_keys=KEYS, rows=payload)
    after_second = _state(db_session, client_id)

    assert first == {"created": 1, "updated": 0, "removed": 0, "kept": 0}
    assert second == {"created": 0, "updated": 1, "removed": 0, "kept": 0}
    assert after_first == after_second, "the same payload left two different roadmaps"
    assert [row[0] for row in after_second] == ["aca-transcript"]


def test_an_omitted_date_leaves_the_row_and_an_explicit_null_clears_it(db_session, require_db):
    """Omission is silence about a field; null is the claim that the row has no date.

    Treating them the same is how a recomputation that computed a suggestion date but no deadline
    silently wiped a stored deadline — a loss the caller cannot see in its own payload.
    """
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    db_session.add(
        RoadmapTask(
            id=str(uuid.uuid4()),
            client_id=client_id,
            material_key="aca-transcript",
            program_id="",
            phase="academic",
            status="pending",
            origin=TaskOrigin.SYSTEM,
            suggested_at=date(2027, 1, 1),
            due_at=date(2027, 2, 1),
            schedule_origin="official",
        )
    )
    db_session.commit()

    # A payload that carries only the suggestion date says nothing about the deadline or the origin.
    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 6, 1)}],
    )
    row = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalar_one()
    assert row.suggested_at == date(2027, 6, 1), "the date the payload stated did not move"
    assert row.due_at == date(2027, 2, 1), "an omitted deadline was cleared"
    assert row.schedule_origin == "official", "an omitted schedule origin was reset"

    # An explicit null is a statement, and that statement clears the field.
    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "due_at": None}],
    )
    assert row.due_at is None, "an explicit null did not clear the deadline"
    assert row.suggested_at == date(2027, 6, 1), "clearing one date cleared another"


def test_a_material_key_or_phase_the_definition_does_not_carry_is_refused(db_session, require_db):
    """The two references a row makes are checked, so neither reaches the columns as a 500.

    `material_key` is a foreign key and used to surface as an `IntegrityError`; `phase` has no foreign
    key and was simply stored. Both are the caller's mistake and both are answered with a message.
    """
    seed_roadmap(db_session)
    client_id = _subject(db_session)

    with pytest.raises(InvalidTaskPayload) as no_material:
        replace_system_tasks(
            db_session,
            client_id,
            applicable_keys=["no-such-material"],
            rows=[{"material_key": "no-such-material", "phase": "academic"}],
        )
    assert "no-such-material" in str(no_material.value)

    with pytest.raises(InvalidTaskPayload) as no_phase:
        replace_system_tasks(
            db_session,
            client_id,
            applicable_keys=KEYS,
            rows=[{"material_key": "aca-transcript", "phase": "banana"}],
        )
    assert "banana" in str(no_phase.value)

    assert _state(db_session, client_id) == [], "a refused payload wrote a row"
