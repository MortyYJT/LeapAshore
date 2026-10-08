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

**The stored rows are written first, and the payload after them.** Moving the first choice from one
program to another — the applicant's new 首选 replaces the old one, and the old one leaves the list —
is the flow this endpoint exists for, and written in payload order it used to be an unmapped 500: the
insert of the new primary row is flushed while the stored row still holds the partial index's
predicate, because SQLAlchemy emits the inserts and updates of one flush before the deletes, and the
removal that would have released the predicate came last. So the stored rows are dealt with first: a
row whose program the payload no longer names is deleted, and a first choice the payload does not keep
is released, and only then is the session flushed and the payload written. After that flush no stored
row holds a first choice the payload does not state, so the one row the payload may mark cannot
collide with anything.

**An omitted ``isPrimary`` in a replacement means ``False``, not "leave it as it is".** The other
fields keep the omission rule — an absent deadline is silence about that deadline, and the stored one
survives — but the first choice is a statement about the portfolio rather than about one row. The
payload lists every row the subject is to hold, so a row that does not claim to be the first choice is
not one, and a caller that moved its first choice to another program says exactly that by naming one
row and not the other. Reading the omission as "leave the stored flag alone" is what left two first
choices in the list — the caller's new one and the stored row it did not mention — which is both a
contradiction and, before this rule, an unmapped 500 through the same flush order. A payload that
wants no first choice states none and gets none.

**A write PostgreSQL refuses anyway is a mapped refusal, not a 500.** The checks below read the
portfolio the caller's own request saw, and a second request for the same subject can commit between
that read and this write; the window cannot be closed by checking harder. The write therefore runs
inside a savepoint and is retried once from a fresh read — the savepoint ``app/deps.py`` and
``app.services.roadmap_tasks`` use for the same race, where the loser of two concurrent writers adopts
what the winner committed instead of failing. An ``IntegrityError`` that survives the retry becomes an
``InvalidApplicationPayload`` naming the constraint PostgreSQL refused, so two tabs of one subject
produce a rebuilt portfolio or a mapped 4xx and never an unmapped 500.

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
from sqlalchemy.exc import IntegrityError
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
    not carry, and — for a caller that bypasses the schema — a row that states no band or no status.
    None of them may reach the applicant as a 500, which is the path an unknown program used to take
    when a foreign key caught what a check should have said out loud.

    It also carries the residue of those checks losing a race with a concurrent writer for the same
    subject: the write runs inside a savepoint and is retried once from a fresh read, and a constraint
    that refuses the retry too is raised here naming what PostgreSQL refused rather than escaping as
    the ``IntegrityError`` a caller cannot read.
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


def _status_of(payload: Any, program_id: str) -> str:
    """The status a row is written with, or a refusal naming the row that states none.

    ``status`` needs the same guard as the band, and for a reason that is easy to miss: a stated
    ``null`` is not silence about the status, it is the claim that the row has no status, and because
    the payload reader stringifies what it is given, storing it literally would write the text
    ``"None"`` into the column — a fourth status the model never defined, which the portfolio lists
    would render as a tag. The schema refuses it for the route; this is the same refusal for the
    caller that reaches the service with a plain mapping, and it is raised before anything is written.
    """
    status = row_value(payload, "status", None)
    if status is None:
        raise InvalidApplicationPayload(
            f"the row for program {program_id!r} states no status: a portfolio row always holds "
            "considering, applying or excluded, and an explicit null is the claim that it holds none. "
            "An omitted status is how 'leave it as it is' is spelled."
        )
    return str(status)


def _apply(payload: Any, row: Application) -> None:
    """Move the fields the applicant owns into the row, and claim it for them.

    A field the payload does not carry is left where it is, which is the rule ``carries`` implements:
    an omitted deadline keeps the stored one, and an explicit ``null`` clears it. ``origin`` is
    written unconditionally rather than read from the payload — the schema refuses the field — so a
    row this call touches is the applicant's afterwards, including a row the advisor had added.

    ``program_id`` is not applied at all: it is the identity the row was matched by, so writing it
    would rename a row rather than restate it.

    ``is_primary`` is the one field that does not keep the omission rule, and it is written
    unconditionally: a whole replacement restates the portfolio's first choice, so a row that does not
    claim the flag is not the first choice. The stored value is deliberately not consulted — see the
    module docstring for the two first choices that "leave it" used to leave behind. ``tier`` and
    ``status`` are the two fields a mapping caller can state as ``null``, so both go through their own
    guard rather than being stringified; ``needs_review`` has a stored default and reads as the schema
    leaves it.

    The band is read here and nowhere else, for a row that is being created as much as for one that is
    being moved: a stored row always has one (the column is ``NOT NULL``), so a row that has none is a
    row this call is about to insert, and the band is as required of it as the schema makes it. A
    payload that states no band therefore still gets a refusal rather than a ``NULL`` insert, without
    the create path computing the band a second time.
    """
    if carries(payload, "tier") or row.tier is None:
        row.tier = _band_of(payload, row.program_id)
    if carries(payload, "status"):
        row.status = _status_of(payload, row.program_id)
    row.is_primary = bool(row_value(payload, "is_primary", False))
    if carries(payload, "official_deadline"):
        row.official_deadline = row_value(payload, "official_deadline")
    if carries(payload, "deadline_source_url"):
        row.deadline_source_url = row_value(payload, "deadline_source_url")
    if carries(payload, "needs_review"):
        row.needs_review = bool(row_value(payload, "needs_review", False))
    row.origin = ApplicationOrigin.USER


def _the_first_choice(rows: Sequence[Any], program_ids: Sequence[str]) -> str | None:
    """The program the payload marks as its first choice, or ``None`` when it marks none.

    ``_reject_a_second_primary`` has already refused a payload that marks more than one, so the first
    match is the only one. A flag the payload omits counts as ``False``, the same reading ``_apply``
    writes with: this is the whole replacement's first choice, not a field of one row.
    """
    for payload, program_id in zip(rows, program_ids):
        if bool(row_value(payload, "is_primary", False)):
            return program_id
    return None


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


def _write_the_replacement(
    session: Session, client_id: str, rows: Sequence[Any], program_ids: Sequence[str]
) -> dict:
    """Write the whole replacement, stored rows first, and report the four counts.

    The two passes and the flush between them are the ordering rule the module docstring gives: the
    stored first choice is released and the dropped rows are deleted *before* the payload may insert
    one of its own, because a flush emits the inserts and updates of one table before the deletes and
    the stored row would otherwise still hold the partial index's predicate.

    The ``before`` snapshots are taken in the first pass, while every stored row still holds the value
    the payload is compared against: releasing a first choice moves the row, and that move is the
    call's own doing rather than a change the applicant asked for, so it must not be what the history
    entry or the ``updated`` count reports.

    Nothing is committed here; the caller owns the savepoint this runs in and the commit after it.
    """
    existing = list(
        session.scalars(select(Application).where(Application.client_id == client_id))
    )
    by_program = {row.program_id: row for row in existing}
    before_by_program = {row.program_id: _snapshot(row) for row in existing}
    wanted = set(program_ids)
    first_choice = _the_first_choice(rows, program_ids)

    # Pass one, the stored rows. A program the payload does not name leaves — whatever `origin` the
    # row carried. This is not a recomputation: nothing here has to leave the advisor's rows alone,
    # because the applicant is the one replacing the whole list. A first choice the payload does not
    # keep is released in the same pass, so the flush below leaves no stored predicate for the
    # payload's own first choice to collide with.
    removed = 0
    for row in existing:
        if row.program_id not in wanted:
            write_history(
                session,
                client_id,
                "removed",
                before_by_program[row.program_id],
                None,
                actor=TaskOrigin.USER,
                application_id=row.id,
            )
            session.delete(row)
            removed += 1
        elif row.is_primary and row.program_id != first_choice:
            row.is_primary = False
    session.flush()

    # Pass two, the payload: what the subject did not hold is inserted, and what it held is moved to
    # what the payload says or left exactly as it is.
    created = updated = kept = 0
    for payload, program_id in zip(rows, program_ids):
        row = by_program.get(program_id)
        if row is None:
            row = Application(
                id=str(uuid.uuid4()),
                client_id=client_id,
                program_id=program_id,
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

        before = before_by_program[program_id]
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

    # Every statement this call makes has now been emitted, so the savepoint the caller opened is
    # what a refused write is taken back to; see `replace_applications`.
    session.flush()
    return {"created": created, "updated": updated, "kept": kept, "removed": removed}


def _the_constraint_that_refused(exc: IntegrityError) -> str:
    """The refusal message for a write PostgreSQL would not take, naming the constraint it says.

    This is the backstop, not the usual path: the checks above read the rows the caller's request saw,
    so a constraint reaching this point means another writer for the same subject committed in
    between, or a caller bypassed the checks. Either way it is a mapped refusal rather than a 500 —
    the raw driver error names a table and an index and nothing the caller can act on — and the two
    constraints that can refuse a portfolio are named so the message says what the shape has to be.
    ``exc.orig.diag`` is psycopg's, and it carries the constraint name; the driver's own words are
    quoted as well, because a future constraint would otherwise be reported without one.
    """
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    named = f" ({constraint})" if constraint else ""
    return (
        f"the portfolio could not be written{named}: the write contradicted a constraint the payload "
        "does not state — UNIQUE (client_id, program_id) allows one row per program and "
        "uq_applications_one_primary_per_client allows one first choice. Two requests for one subject "
        "in flight at the same time are what produce it; sending the same payload again against the "
        f"stored portfolio resolves the race. PostgreSQL said: {exc.orig}"
    )


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

    That commit is the last step of an attempt, and there are two of them. The first runs against the
    portfolio this call just read; if PostgreSQL refuses it, the savepoint is rolled back and the
    second attempt reads the portfolio again and states the payload on top of what the winning writer
    committed. The savepoint is what makes the second attempt possible: a failed statement aborts a
    PostgreSQL transaction, and rolling back to the savepoint returns this session to a usable state
    without discarding the statements before it — the same mechanism ``app/deps.py`` uses for two
    first contacts and ``app.services.roadmap_tasks`` for two recomputations. A refusal that survives
    the second attempt is raised as an ``InvalidApplicationPayload``, because by then the payload has
    been tried against the stored portfolio twice and the caller is the one who can do something
    about it.
    """
    program_ids = _program_ids(rows)
    _reject_a_program_named_twice(program_ids)
    _reject_a_second_primary(rows, program_ids)
    _reject_unknown_programs(session, program_ids)

    for attempt in (1, 2):
        try:
            with session.begin_nested():
                counts = _write_the_replacement(session, client_id, rows, program_ids)
        except IntegrityError as exc:
            if attempt == 2:
                raise InvalidApplicationPayload(_the_constraint_that_refused(exc)) from exc
            # The savepoint has undone this attempt — the rows it inserted are gone and the rows it
            # moved are back to what they were — while the writer that won has committed, so the next
            # attempt starts from what is actually stored. `begin_nested` takes its snapshot before
            # this call writes anything, so nothing of this attempt is left to be written twice.
            continue
        # All the statements were emitted inside the savepoint, and none of this table's constraints
        # is deferrable, so this commit only ends the transaction.
        session.commit()
        return counts
