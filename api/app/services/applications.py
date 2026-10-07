"""Replace one applicant's school-choice portfolio, whole, in one transaction.

This module is the writer behind `PUT /api/applications`. The applicant ticks the programs they want
and the browser hands the server the resulting list; the server's job is to make the stored portfolio
say exactly that and nothing else. So, in one call:

- a program the payload names that the subject does not hold is inserted;
- a row the subject already holds and the payload restates is moved to what the payload says, or left
  exactly as it is when the payload moves nothing;
- a row the subject holds whose program the payload no longer names is removed.

The row's identity is the program, not the row id: `UNIQUE (client_id, program_id)` makes one program
one row, so the caller keys its payload by program and does not have to know the ids the database
handed out. Everything runs against one snapshot taken at the top and commits once at the end, so a
failure cannot leave a portfolio half-replaced.

**The two refusals are deliberately different messages.** The table has two constraints and a payload
can break either. The same program named by two rows breaks `UNIQUE (client_id, program_id)`; two rows
marked ``isPrimary`` break the partial unique index ``uq_applications_one_primary_per_client``. Both
are the caller's mistake, so both are raised here before anything is written and served as a 422 that
names the offender — the alternative, letting PostgreSQL raise, is the same 500 for two different
problems and tells the applicant nothing about which rule their list broke. A single shared "invalid
portfolio" message would be the same defect one layer up, so the two checks name different things: one
says a program was named more than once, the other says more than one row claims to be the first
choice.

``origin`` is the server's to write, never the caller's to send: a portfolio is the applicant's own
decision, so every row this call stores says ``user``. A row the advisor had added and the applicant
re-states becomes the applicant's, because restating a choice is claiming it — which is also why a
program the payload drops is removed whatever ``origin`` it carried: this is the applicant replacing
their portfolio, not a recomputation that must leave rows it does not own alone (that rule is
``app.services.roadmap_tasks``, where a row's owner is the whole point).

Every insert, move and removal appends a ``task_events`` entry with ``actor="user"`` and a before /
after snapshot, through the same writer the roadmap service uses, so the two doors onto an applicant's
data are read the same way afterwards. A row the payload restates without moving anything writes no
entry: an entry whose two sides are equal would say something happened at a moment when nothing did.
"""

import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationOrigin
from app.models.program import Program
from app.models.task import TaskOrigin
from app.services.writes import carries, row_value, write_history


class InvalidApplicationPayload(ValueError):
    """A portfolio that cannot be stored, with the reason in the message.

    Raised before anything is written, so a rejected payload leaves the portfolio exactly as it was
    and the route can answer with a 4xx. Every member is the caller's mistake rather than a server
    fault: the same program named twice, more than one first choice, a program id the catalogue does
    not carry, and — for a caller that bypasses the schema — a row that states no band. None of them
    may reach the applicant as a 500, which is the path an unknown program used to take when a
    foreign key caught what a check should have said out loud.
    """


def _snapshot(row: Application) -> dict:
    """The fields worth keeping in the history, as JSON-safe scalars.

    ``official_deadline`` is a ``date`` and therefore not JSON, so the snapshot carries the ISO string
    the column holds. A snapshot read back identically is all the history needs, and the identity
    ``program_id`` is in it because the entry outlives the row: after a removal there is nothing else
    left to say which choice the applicant dropped.
    """
    return {
        "program_id": row.program_id,
        "tier": row.tier,
        "status": row.status,
        "is_primary": row.is_primary,
        "official_deadline": (
            row.official_deadline.isoformat() if row.official_deadline else None
        ),
        "deadline_source_url": row.deadline_source_url,
        "needs_review": row.needs_review,
        "origin": row.origin,
    }


def _program_ids(rows: Sequence[Any]) -> list[str]:
    """The programs the payload names, in payload order, as the column stores them."""
    return [str(row_value(row, "program_id", "") or "") for row in rows]


def _reject_a_program_named_twice(program_ids: Sequence[str]) -> None:
    """Refuse a payload that puts one program in the portfolio twice.

    The row's identity is the program, so two rows naming one program are the same choice written
    twice rather than two choices. Stored literally it is an ``IntegrityError`` on
    ``UNIQUE (client_id, program_id)``, and the two rows may disagree about the band, the status and
    the deadline — so "keep the last" would silently drop a decision the applicant made. The refusal
    names the programs, because a list of ten rows gives the caller no way to find the repetition.
    """
    repeated = sorted(
        program_id for program_id, count in Counter(program_ids).items() if count > 1
    )
    if repeated:
        raise InvalidApplicationPayload(
            f"program(s) {repeated} are named by more than one row: a portfolio holds one row per "
            "program, and UNIQUE (client_id, program_id) is the constraint that says so. Two rows for "
            "one program are the same choice written twice, and they may disagree."
        )


def _reject_a_second_primary(rows: Sequence[Any], program_ids: Sequence[str]) -> None:
    """Refuse a payload that claims more than one first choice.

    This is the partial unique index ``uq_applications_one_primary_per_client`` and it is a separate
    constraint from the program uniqueness above: the rows here name different programs, so the
    program key cannot be what refuses them. The check runs after the duplicate check, so a payload
    that is wrong in both ways is reported as a repetition first and does not come back with one
    merged message.
    """
    primaries = [
        program_id
        for row, program_id in zip(rows, program_ids)
        if bool(row_value(row, "is_primary", False))
    ]
    if len(primaries) > 1:
        raise InvalidApplicationPayload(
            f"the payload marks {len(primaries)} rows as the first choice ({primaries}): at most one "
            "row per applicant may be primary, which is the partial unique index "
            "uq_applications_one_primary_per_client. A portfolio has one 首选, so this list cannot be "
            "stored as it stands."
        )


def _reject_unknown_programs(session: Session, program_ids: Sequence[str]) -> None:
    """Refuse program ids the catalogue does not carry, before the foreign key would.

    ``program_id`` is a foreign key, so an unknown id used to surface as an ``IntegrityError`` and a
    500; the caller can act on the mistake, so it is checked here and answered with a message that
    names the ids. This is a fact about the rows ``programs`` currently holds rather than about the
    shape of a payload, which is why it is checked here and not in the schema.
    """
    wanted = sorted(set(program_ids))
    known = set(session.scalars(select(Program.id).where(Program.id.in_(wanted))))
    unknown = [program_id for program_id in wanted if program_id not in known]
    if unknown:
        raise InvalidApplicationPayload(
            f"program id(s) {unknown} name no program in the catalogue: a portfolio row is a choice "
            "of a program the applicant can apply to, so a row for an unknown one could never be "
            "rendered or applied to."
        )


def _band_of(payload: Any, program_id: str) -> str:
    """The band a row is written with, or a refusal naming the row that states none.

    The schema already refuses a missing or misspelled band, and this covers the part a mapping caller
    can still get wrong: ``replace_applications`` is callable without a schema in front of it, and a
    row with no band would otherwise reach the ``NOT NULL`` column as an ``IntegrityError`` — or, on an
    update, be stored as the text ``"None"``. The membership of 冲 / 稳 / 保 stays the schema's
    question, which is what the model means by saying that schema is where the row enters the system.
    """
    band = row_value(payload, "tier", None)
    if band is None:
        raise InvalidApplicationPayload(
            f"the row for program {program_id!r} states no tier: every portfolio row is placed in the "
            "冲 / 稳 / 保 band the applicant chose, so a replacement may not leave one blank."
        )
    return str(band)


def _apply(payload: Any, row: Application) -> None:
    """Move the fields the applicant owns into the row, and claim it for them.

    A field the payload does not carry is left where it is, which is the rule ``carries`` implements:
    an omitted deadline keeps the stored one, and an explicit ``null`` clears it. ``origin`` is
    written unconditionally rather than read from the payload — the schema refuses the field — so a
    row this call touches is the applicant's afterwards, including a row the advisor had added.

    ``program_id`` is not applied at all: it is the identity the row was matched by, so writing it
    would rename a row rather than restate it.

    ``status``, ``is_primary`` and ``needs_review`` are read as the schema leaves them: it refuses a
    ``null`` for all three, so a mapping caller that bypasses it is the only one that can send one.
    ``tier`` is the exception, and goes back through ``_band_of`` rather than being stringified —
    ``bool``/``str`` would quietly turn a ``null`` into ``"None"``, which is a band the portfolio
    lists would then render as a tag.
    """
    if carries(payload, "tier"):
        row.tier = _band_of(payload, row.program_id)
    if carries(payload, "status"):
        row.status = str(row_value(payload, "status", row.status))
    if carries(payload, "is_primary"):
        row.is_primary = bool(row_value(payload, "is_primary", False))
    if carries(payload, "official_deadline"):
        row.official_deadline = row_value(payload, "official_deadline")
    if carries(payload, "deadline_source_url"):
        row.deadline_source_url = row_value(payload, "deadline_source_url")
    if carries(payload, "needs_review"):
        row.needs_review = bool(row_value(payload, "needs_review", False))
    row.origin = ApplicationOrigin.USER


def _name_the_change(before: dict, after: dict) -> str:
    """The event name for one row that moved, from the field that moved.

    Three of the names are the ones the design's event vocabulary already carries for an application:
    ``status_changed`` when the status moved, ``rescheduled`` when a deadline or the url it cites did,
    and ``reassigned`` when the only thing that changed is the row's owner — which is what the
    advisor-to-applicant claim is. The order is the order of consequence, so an edit that moves two of
    them is recorded once, under the first, with both in the snapshot.

    What is left is a change to the band, the first-choice flag or the by-hand flag, and the design has
    no word for it because it has no counterpart on a task row. It is recorded as ``updated`` rather
    than forced under one of the three names above, each of which means something else: a retiered row
    reported as ``rescheduled`` would say a date moved when none did.
    """
    if before["status"] != after["status"]:
        return "status_changed"
    if (before["official_deadline"], before["deadline_source_url"]) != (
        after["official_deadline"],
        after["deadline_source_url"],
    ):
        return "rescheduled"
    if before["origin"] != after["origin"]:
        return "reassigned"
    return "updated"


def replace_applications(session: Session, client_id: str, rows: Sequence[Any]) -> dict:
    """Make this subject's portfolio say exactly what ``rows`` says, and report what moved.

    Returns ``{"created": n, "updated": n, "kept": n, "removed": n}``. The four counts are disjoint
    and together describe the call: ``created`` and ``updated`` are the rows this call wrote,
    ``removed`` the rows it deleted, and ``kept`` the existing rows the payload restated without
    moving anything. ``updated + kept + removed`` is therefore what the subject held before, and
    ``created + updated + kept`` is what it holds after, which is how a caller checks the count it
    cares about instead of trusting the status code.

    The payload is checked against the catalogue and against the table's own constraints before the
    first write, so a refused call leaves the portfolio exactly as it was — see
    ``InvalidApplicationPayload``, and the module docstring for why the two constraint refusals are
    two different messages. The write commits once, at the end.
    """
    program_ids = _program_ids(rows)
    _reject_a_program_named_twice(program_ids)
    _reject_a_second_primary(rows, program_ids)
    _reject_unknown_programs(session, program_ids)

    existing = list(
        session.scalars(select(Application).where(Application.client_id == client_id))
    )
    by_program = {row.program_id: row for row in existing}
    wanted = set(program_ids)

    created = updated = kept = removed = 0
    for payload, program_id in zip(rows, program_ids):
        row = by_program.get(program_id)
        if row is None:
            row = Application(
                id=str(uuid.uuid4()),
                client_id=client_id,
                program_id=program_id,
                tier=_band_of(payload, program_id),
                origin=ApplicationOrigin.USER,
            )
            _apply(payload, row)
            session.add(row)
            write_history(
                session,
                client_id,
                "created",
                None,
                _snapshot(row),
                actor=TaskOrigin.USER,
                application_id=row.id,
            )
            created += 1
            continue

        before = _snapshot(row)
        _apply(payload, row)
        after = _snapshot(row)
        if before == after:
            # The payload restated this row and nothing moved. It stays, and it writes no history,
            # because an entry with equal sides would report a change that did not happen.
            kept += 1
            continue
        write_history(
            session,
            client_id,
            _name_the_change(before, after),
            before,
            after,
            actor=TaskOrigin.USER,
            application_id=row.id,
        )
        updated += 1

    for row in existing:
        if row.program_id in wanted:
            continue
        # The applicant's whole portfolio is what the payload says it is, so a program it does not
        # name leaves — whatever `origin` the row carried. This is not a recomputation: nothing here
        # has to leave the advisor's rows alone, because the applicant is the one replacing the list.
        write_history(
            session,
            client_id,
            "removed",
            _snapshot(row),
            None,
            actor=TaskOrigin.USER,
            application_id=row.id,
        )
        session.delete(row)
        removed += 1

    session.commit()
    return {"created": created, "updated": updated, "kept": kept, "removed": removed}
