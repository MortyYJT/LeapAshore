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

Leaving the two lists free to disagree is a worse defect than either claim being wrong on its own. A
key that ``rows`` carries and ``applicable_keys`` does not is a contradiction: sending a row is the
caller's own statement that the key is applicable this round. Implemented literally, one call writes
that row and then the removal pass deletes a row with the same key, and what the call did depends on
state the caller cannot see — a row created by this very call survives, because the removal pass walks
a snapshot taken before the loop, while an identical row that already existed is updated and then
destroyed. The same payload therefore leaves a row behind or removes one depending on whether it was
there before, which is not a rule anyone can hold in their head. ``InvalidTaskPayload`` rejects the
contradiction instead, before anything is written, and the route serves it as a 422 naming the keys.
For the same reason the payload is checked against the definition first: a ``materialKey`` that names
no ``material_templates`` row would otherwise be an ``IntegrityError`` and a raw 500, and a ``phase``
that names no ``roadmap_phases`` row would be stored as a place outside the timeline.

Two recomputations for one subject can also reach the insert for the same identity at the same time —
two tabs, a retried request, a proxy replaying one. The insert therefore runs inside a savepoint whose
``IntegrityError`` is the second caller losing that race, exactly as ``load_or_create_profile`` in
``app/deps.py`` treats a racing first contact: releasing the savepoint undoes only the failed insert,
the row the winner committed is read back, and this call updates it as the ``system`` row it is
instead of one of two identical requests coming back as a 500.

Every change writes a ``task_events`` row with ``actor="system"`` and a before/after snapshot, so the
ownership rule can be audited after the fact rather than being taken on trust. The whole replacement
runs in one transaction, so a partial write cannot leave the roadmap half-updated.

``update_task`` is the module's other writer, and it is the same rule seen from the applicant's side.
It is the per-row edit: the applicant changes one row's status or dates, so the row is looked up by
``(id, client_id)`` together — a row belonging to another subject is a miss rather than a success, and
the two cases are deliberately indistinguishable to the caller — and the edit claims the row by setting
``origin`` to ``user``, which is what makes a later recomputation leave it alone. A row the advisor
already owns is the one exception: changing its status does not transfer its provenance, because the
advisor still owns why the row exists. Its history is written with ``actor="user"``, so the two doors
onto a row are told apart in the audit trail rather than merged into one "something changed".
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.task import RoadmapTask, ScheduleOrigin, TaskEvent, TaskOrigin, TaskStatus


class InvalidTaskPayload(ValueError):
    """A recomputation that cannot be applied, with the reason in the message.

    Raised before anything is written, so a rejected payload leaves the roadmap exactly as it was and
    the route can answer with a 4xx: a payload that contradicts itself, one that names a material key
    the definition does not carry, one that names a phase it does not carry, and the residue of those
    checks losing a race with a concurrent definition change. None of them is a server fault, so none
    of them may reach the applicant as a 500 — the path an unknown material key used to take, where a
    foreign key caught what a check should have said out loud.
    """


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    """Read one field from a payload row, which may be a schema object or a plain mapping.

    The router passes ``TaskIn`` instances and the tests pass dicts, and both spell a field the same
    way. A missing key answers with the default rather than raising, and ``_carries`` is what tells
    the two apart: the default is for a field the payload never mentions, while a value the payload
    does state — including an explicit ``None`` — is applied as it stands.
    """
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _carries(row: Any, name: str) -> bool:
    """True when the payload states this field, as opposed to leaving it to a default.

    The distinction is what makes a recomputation a partial update. A payload that omits a date is
    silent about that date, so the row keeps the one it has; sending ``null`` is the claim that the
    row has no date, and that is what clears it. Without the distinction, a caller that computed a
    suggestion date but no deadline would silently wipe a deadline the row held — a loss the caller
    cannot see in its own payload, which is exactly the kind of state change this batch exists to
    prevent.
    """
    if isinstance(row, Mapping):
        return name in row
    fields_set = getattr(row, "model_fields_set", None)
    if fields_set is not None:
        return name in fields_set
    return hasattr(row, name)


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
    actor: str = TaskOrigin.SYSTEM,
) -> None:
    """Append one entry to the audit trail, attributed to whoever made the change.

    ``actor`` defaults to the client's own recomputation, which is every call in
    ``replace_system_tasks``; ``update_task`` passes ``TaskOrigin.USER`` instead, so an entry says
    which door the change came through and not merely that a row moved.
    """
    session.add(
        TaskEvent(
            id=str(uuid.uuid4()),
            client_id=client_id,
            task_id=task_id,
            actor=actor,
            event=event,
            before=before,
            after=after,
        )
    )


def _reject_a_contradiction(identities: Sequence[tuple[str, str]], applicable: set[str]) -> None:
    """Refuse a payload whose rows claim keys its own ``applicable_keys`` denies.

    See the module docstring: the two lists describe one fact, and honouring both in one call is what
    makes the outcome depend on whether the row happened to exist already.
    """
    contradictory = sorted({key for key, _ in identities if key not in applicable})
    if contradictory:
        raise InvalidTaskPayload(
            f"rows carries material key(s) {contradictory} that applicable_keys does not list: a row "
            "the caller computed is itself the statement that the key is applicable this round, so "
            "the two lists disagree. Listing every row's key in applicable_keys resolves it."
        )


def _reject_unknown_references(
    session: Session, identities: Sequence[tuple[str, str]], rows: Sequence[Any]
) -> None:
    """Refuse keys and phases the definition does not carry, before the columns would.

    ``material_key`` is a foreign key, so an unknown one used to surface as an ``IntegrityError`` and
    a 500; ``phase`` has no foreign key, so an unknown one was simply stored and the row sorted
    nowhere. Both are mistakes the caller can act on, and both are checked here rather than in the
    schema because they are facts about the rows the definition currently holds, not about the shape
    of a payload — the phase list is data transcribed from ``web/lib/roadmap.ts``, so a hand-written
    enum naming it would go stale the first time a phase was added.
    """
    keys = sorted({key for key, _ in identities})
    if keys:
        known_keys = set(
            session.scalars(select(MaterialTemplate.key).where(MaterialTemplate.key.in_(keys)))
        )
        unknown_keys = [key for key in keys if key not in known_keys]
        if unknown_keys:
            raise InvalidTaskPayload(
                f"material key(s) {unknown_keys} name no material_template: the roadmap definition "
                "does not carry them, so a row for them could never be rendered."
            )

    phases = sorted({str(_row_value(row, "phase", "")) for row in rows})
    if phases:
        known_phases = set(
            session.scalars(select(RoadmapPhase.key).where(RoadmapPhase.key.in_(phases)))
        )
        unknown_phases = [phase for phase in phases if phase not in known_phases]
        if unknown_phases:
            raise InvalidTaskPayload(
                f"phase(s) {unknown_phases} name no roadmap phase: a row is placed by the phase the "
                "definition serves, and an unknown one would put it outside the timeline."
            )


def _apply_dates(row: RoadmapTask, payload: Any) -> None:
    """Move the fields the recomputation owns, and leave the applicant's marks alone.

    The four that can move are ``phase``, ``suggested_at``, ``due_at`` and ``schedule_origin``: the
    phase is derived from the definition the client recomputed against, and the schedule origin says
    whether the date came from a suggestion or an official deadline, so it travels with the dates.
    ``status`` and ``completed_at`` are the applicant's marks and are deliberately absent here.

    A field the payload does not carry is left where it is; see ``_carries``. ``program_id`` is not
    applied at all: it is half of the identity a row was matched by, so writing it would rename a row
    rather than update it.
    """
    if _carries(payload, "phase"):
        row.phase = str(_row_value(payload, "phase", row.phase))
    if _carries(payload, "suggested_at"):
        row.suggested_at = _row_value(payload, "suggested_at")
    if _carries(payload, "due_at"):
        row.due_at = _row_value(payload, "due_at")
    if _carries(payload, "schedule_origin"):
        row.schedule_origin = str(
            _row_value(payload, "schedule_origin", ScheduleOrigin.SUGGESTED)
            or ScheduleOrigin.SUGGESTED
        )


def _reload(session: Session, client_id: str, identity: tuple[str, str]) -> RoadmapTask | None:
    """Read one row back by identity, after a failed insert released its savepoint."""
    return session.execute(
        select(RoadmapTask).where(
            RoadmapTask.client_id == client_id,
            RoadmapTask.material_key == identity[0],
            RoadmapTask.program_id == identity[1],
        )
    ).scalar_one_or_none()


def replace_system_tasks(
    session: Session,
    client_id: str,
    applicable_keys: Sequence[str],
    rows: Sequence[Any],
) -> dict:
    """Replace the rows this client generated, and only those.

    Returns ``{"created": n, "updated": n, "removed": n, "kept": n}``. The four counts are disjoint:
    ``created`` and ``updated`` are the rows this call wrote, ``removed`` the rows it deleted, and
    ``kept`` the existing rows it left exactly as they were — every ``user``/``agent`` row, which the
    rule forbids it to touch, and every ``system`` row whose key the caller still lists as applicable
    without sending a row for it. Nothing is counted twice, so the four together describe the call.

    The caller states ``applicable_keys`` separately from ``rows`` on purpose; see the module docstring
    for the deletion that prevents and for why a key only one of the two lists carries is rejected
    rather than interpreted. The whole replacement commits once, at the end.
    """
    applicable = set(applicable_keys)
    identities = [_payload_key(payload) for payload in rows]
    _reject_a_contradiction(identities, applicable)
    _reject_unknown_references(session, identities, rows)

    existing = list(
        session.execute(select(RoadmapTask).where(RoadmapTask.client_id == client_id)).scalars()
    )
    by_identity = {(row.material_key, row.program_id): row for row in existing}
    written: set[str] = set()

    created = updated = 0
    for payload, identity in zip(rows, identities):
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
            # Everything an earlier row left pending is flushed first, so the savepoint below can
            # only ever undo this row's own insert: a pending event from an earlier row would
            # otherwise be emitted inside this savepoint and expunged with it.
            session.flush()
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError as exc:
                # Another recomputation for this subject inserted this identity between the snapshot
                # above and this insert. The savepoint has undone only this insert, and the winner
                # has committed, so the row is read back and handled as an existing one.
                row = _reload(session, client_id, identity)
                if row is None:
                    raise InvalidTaskPayload(
                        f"the row for material key {identity[0]!r} and program {identity[1]!r} could "
                        "not be written: the subject or the material it names is no longer in the "
                        f"database ({exc.orig})"
                    ) from exc
                by_identity[identity] = row
            else:
                by_identity[identity] = row
                _history(session, client_id, row.id, "created", None, _snapshot(row))
                created += 1
                written.add(row.id)
                continue

        if row.origin != TaskOrigin.SYSTEM:
            # A human's or the advisor's row. It is not the recomputation's to change, so it is not
            # even read: the payload's dates are dropped on purpose rather than applied.
            continue

        before = _snapshot(row)
        _apply_dates(row, payload)
        _history(session, client_id, row.id, "rescheduled", before, _snapshot(row))
        updated += 1
        written.add(row.id)

    removed = 0
    removed_ids: set[str] = set()
    for row in existing:
        # Only a system row, and only when the caller said the key itself is no longer applicable.
        # A row the caller never mentioned — including every user and agent row — falls through here.
        if row.origin != TaskOrigin.SYSTEM or row.material_key in applicable:
            continue
        _history(session, client_id, row.id, "removed", _snapshot(row), None)
        session.delete(row)
        removed_ids.add(row.id)
        removed += 1

    session.commit()
    # What the call left alone, read off the snapshot rather than assumed: a row another
    # recomputation inserted is not one of this call's existing rows and is never counted here, so
    # the count cannot go wrong the way `len(existing) - removed` did when a row was both updated and
    # subtracted.
    kept = len({row.id for row in existing} - written - removed_ids)
    return {"created": created, "updated": updated, "removed": removed, "kept": kept}


def _name_the_user_edit(before: dict, after: dict) -> str | None:
    """The event name for one edit, from the field that moved, or ``None`` if none did.

    The three names are the ones the design's event vocabulary carries for a row that already exists:
    ``status_changed`` when the status moved, ``rescheduled`` when only a date did, and ``reassigned``
    when the only thing that changed is the row's owner — which is what the ``system``-to-``user`` flip
    is. The order is the order of consequence: an edit that moves two of them is recorded once, under
    the first, with all of them in the snapshot.
    """
    if before["status"] != after["status"]:
        return "status_changed"
    if before["suggested_at"] != after["suggested_at"] or before["due_at"] != after["due_at"]:
        return "rescheduled"
    if before["origin"] != after["origin"]:
        return "reassigned"
    return None


def update_task(
    session: Session, client_id: str, task_id: str, patch: Any
) -> RoadmapTask | None:
    """Apply one applicant's edit to one of their own rows, or miss.

    Returns the row it wrote, or ``None`` when no row with that id belongs to this subject. The lookup
    asks the two questions as one — ``id`` and ``client_id`` in the same ``WHERE`` — because a route
    that read the row by id and only then compared owners would already have another subject's row in
    its session, and the difference between "there is no such row" and "that one is not yours" is
    exactly the difference a caller should not be able to read. Both are the same miss, and the route
    serves both as the same 404.

    The fields the applicant owns are ``status`` and the two dates. ``origin`` is set to ``user`` as
    soon as an edit lands, because that is what "the applicant owns this row now" means and it is what
    makes the next recomputation skip the row (see ``replace_system_tasks``) — with one exception: a
    row that is already ``agent`` keeps its origin, since the advisor still owns why the row exists and
    a status change is not a transfer of provenance. ``program_id``, ``material_key`` and ``phase`` are
    not applied at all; the schema refuses them before this function sees a payload, the same way it
    refuses ``origin``.

    ``completed_at`` travels with ``status`` rather than with the caller: entering ``completed`` stamps
    it with the moment of the edit, leaving ``completed`` clears it, and a status that does not move
    leaves it alone. Only a move writes it, so re-sending ``completed`` for a row that is already
    completed does not restamp history with a later moment. A date the payload does not carry is left
    where it is; an explicit ``null`` clears it; see ``_carries``.

    One ``TaskEvent`` with ``actor="user"`` records the edit when a field moved, snapshotted by the
    same ``_snapshot`` the recomputation uses, so both doors onto a row are read the same way in the
    audit trail. A request that moved nothing writes nothing: the schema refuses a patch that states no
    field, so the only way to reach here with no change is a caller re-sending a value the row already
    holds, and an entry whose ``before`` and ``after`` are equal would say "something happened" about a
    moment when nothing did. The write commits once, at the end.
    """
    row = session.execute(
        select(RoadmapTask).where(
            RoadmapTask.id == task_id,
            RoadmapTask.client_id == client_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    before = _snapshot(row)
    if _carries(patch, "status"):
        status = str(_row_value(patch, "status"))
        if status != row.status:
            if status == TaskStatus.COMPLETED:
                row.completed_at = datetime.now(timezone.utc)
            elif row.status == TaskStatus.COMPLETED:
                row.completed_at = None
            row.status = status
    if _carries(patch, "suggested_at"):
        row.suggested_at = _row_value(patch, "suggested_at")
    if _carries(patch, "due_at"):
        row.due_at = _row_value(patch, "due_at")
    if row.origin != TaskOrigin.AGENT:
        row.origin = TaskOrigin.USER

    after = _snapshot(row)
    event = _name_the_user_edit(before, after)
    if event is not None:
        _history(session, client_id, row.id, event, before, after, actor=TaskOrigin.USER)

    session.commit()
    return row
