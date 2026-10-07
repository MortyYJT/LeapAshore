"""Write the rows a recomputation generated, and nothing else.

This module is the `origin` rule from the M2 design (sections 3.2, 3.3 and 3.8) in one place. Every
task row says who owns it, and only the rows the client itself generated may be replaced by a
recomputation:

- a row that exists and is ``system`` is updated, but only in the fields the client derives. ``status``
  and ``completed_at`` are the applicant's own marks, so a recompute that recomputed them would
  silently untick a finished requirement — the loss the rule exists to prevent.
- a row a human or the advisor owns is not touched at all, not even its dates. It is not part of the
  recomputation's output, so there is nothing for the recomputation to say about it.
- a key the client computed but that has no row yet is created as a ``system`` row in ``pending``.

The third claim is the one that needs the caller's help, so it arrives as an argument rather than
being inferred. ``applicable_keys`` is the set of material keys that are applicable this round, stated
**separately from the rows**: "this key is no longer applicable" and "this payload does not mention
this key" are different claims, and only a ``system`` row whose key is genuinely absent from
``applicable_keys`` is removed. Reading the second as the first is a real defect rather than a
theoretical one — the definition read can fall back to the frontend's built-in constants, which
deliberately omit the visa phase, so a recomputation driven by that fallback would compute no visa
materials and delete the visa rows; the next run with the real definition would recreate them as
``pending`` and the applicant's completion state would be gone. A ``user`` or ``agent`` row is never a
candidate for removal under either claim, because the recomputation does not own it.

Every change writes a ``task_events`` row with ``actor="system"`` and a before/after snapshot, so the
ownership rule can be audited after the fact rather than being taken on trust. The whole replacement
runs in one transaction, so a partial write cannot leave the roadmap half-updated.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task import RoadmapTask, ScheduleOrigin, TaskEvent, TaskOrigin, TaskStatus


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    """Read one field from a payload row, which may be a schema object or a plain mapping.

    The router passes ``TaskIn`` instances and the tests pass dicts, and both spell a field the same
    way. A missing key answers with the default rather than raising: ``None`` is the honest answer for
    a date the client computed as unknown, and getting that wrong would be a 500 on a field an
    applicant never filled in.
    """
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _payload_key(row: Any) -> tuple[str, str]:
    """The identity a row is matched by: ``(material_key, program_id)``.

    ``program_id`` defaults to the empty string, which is the value the column and its uniqueness
    constraint use for a material that is not tied to one program. It is normalised here rather than
    passed through, so a caller that omits it and a caller that sends ``""`` address the same row.
    """
    return str(_row_value(row, "material_key", "")), str(_row_value(row, "program_id", "") or "")


def _snapshot(row: RoadmapTask) -> dict:
    """The fields worth keeping in the history, as JSON-safe scalars.

    ``date`` and ``datetime`` are not JSON, so the snapshots carry ISO strings. The event table holds
    history rather than state, and a string that reads back identically is enough for it.

    The two kinds of timestamp are spelled deliberately differently, because they mean different
    things: a date is a day with no time attached, while the stored ``completed_at`` is read back as
    UTC, so its offset is dropped and a ``Z`` is appended. Serialising it the default way instead
    gives ``+00:00``, and the two spellings alternate within one run because SQLAlchemy hands back
    the live object for a row written in this transaction and a re-read one for a row that is not —
    a difference in the history that has nothing to do with what happened.
    """
    return {
        "material_key": row.material_key,
        "program_id": row.program_id,
        "phase": row.phase,
        "status": row.status,
        "suggested_at": row.suggested_at.isoformat() if row.suggested_at else None,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "schedule_origin": row.schedule_origin,
        "origin": row.origin,
        "completed_at": (
            row.completed_at.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
            if row.completed_at
            else None
        ),
    }


def _history(
    session: Session,
    client_id: str,
    task_id: str | None,
    event: str,
    before: dict | None,
    after: dict | None,
) -> None:
    """Append one entry to the audit trail. ``actor`` is always the client's own recomputation."""
    session.add(
        TaskEvent(
            id=str(uuid.uuid4()),
            client_id=client_id,
            task_id=task_id,
            actor=TaskOrigin.SYSTEM,
            event=event,
            before=before,
            after=after,
        )
    )


def _apply_dates(row: RoadmapTask, payload: Any) -> None:
    """Move the fields the recomputation owns, and leave the applicant's marks alone.

    The four that move are ``phase``, ``suggested_at``, ``due_at`` and ``schedule_origin``: the phase
    is derived from the definition the client recomputed against, and the schedule origin says whether
    the date came from a suggestion or an official deadline, so it travels with the dates. ``status``
    and ``completed_at`` are the applicant's marks and are deliberately absent here.

    The payload's ``program_id`` is not applied: it is half of the identity a row was matched by, so
    writing it would rename a row rather than update it.
    """
    row.phase = str(_row_value(payload, "phase", row.phase))
    row.suggested_at = _row_value(payload, "suggested_at", None)
    row.due_at = _row_value(payload, "due_at", None)
    row.schedule_origin = str(
        _row_value(payload, "schedule_origin", ScheduleOrigin.SUGGESTED) or ScheduleOrigin.SUGGESTED
    )


def replace_system_tasks(
    session: Session,
    client_id: str,
    applicable_keys: Sequence[str],
    rows: Sequence[Any],
) -> dict:
    """Replace the rows this client generated, and only those.

    Returns ``{"created": n, "updated": n, "removed": n, "kept": n}``. ``kept`` counts every existing
    row that survived, which is both the ``user``/``agent`` rows nothing may touch and the ``system``
    rows whose key the caller still lists as applicable without sending a row for them.

    The caller states ``applicable_keys`` separately from ``rows`` on purpose; see the module docstring
    for the deletion it prevents. The whole replacement commits once, at the end.
    """
    applicable = set(applicable_keys)

    existing = list(
        session.execute(select(RoadmapTask).where(RoadmapTask.client_id == client_id)).scalars()
    )
    by_identity = {(row.material_key, row.program_id): row for row in existing}

    created = updated = 0
    for payload in rows:
        identity = _payload_key(payload)
        row = by_identity.get(identity)
        if row is None:
            row = RoadmapTask(
                id=str(uuid.uuid4()),
                client_id=client_id,
                material_key=identity[0],
                program_id=identity[1],
                phase=str(_row_value(payload, "phase", "")),
                status=TaskStatus.PENDING,
                origin=TaskOrigin.SYSTEM,
            )
            _apply_dates(row, payload)
            session.add(row)
            by_identity[identity] = row
            _history(session, client_id, row.id, "created", None, _snapshot(row))
            created += 1
            continue

        if row.origin != TaskOrigin.SYSTEM:
            # A human's or the advisor's row. It is not the recomputation's to change, so it is not
            # even read: the payload's dates are dropped on purpose rather than applied.
            continue

        before = _snapshot(row)
        _apply_dates(row, payload)
        _history(session, client_id, row.id, "rescheduled", before, _snapshot(row))
        updated += 1

    removed = 0
    for row in existing:
        # Only a system row, and only when the caller said the key itself is no longer applicable.
        # A row the caller never mentioned — including every user and agent row — falls through here.
        if row.origin != TaskOrigin.SYSTEM or row.material_key in applicable:
            continue
        _history(session, client_id, row.id, "removed", _snapshot(row), None)
        session.delete(row)
        removed += 1

    session.commit()
    return {"created": created, "updated": updated, "removed": removed, "kept": len(existing) - removed}
