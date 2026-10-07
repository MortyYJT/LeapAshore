"""The roadmap task schema: one applicant's rows, and the payload that replaces the client's own.

`RoadmapTask` is per-applicant state, and this module carries both directions of it. A row read out of
the database leaves as ``TaskOut``; a recomputation arrives as ``TaskReplaceRequest``, which is the
rows plus the separate statement of which material keys are applicable this round.

That second list is the whole reason the request has a shape of its own rather than being a bare
array of rows. "This key is no longer applicable" and "this payload does not carry this key" are
different claims, and the service deletes only on the first (design section 3.8): the definition read
falls back to the frontend's built-in constants, which omit the visa phase, so a recomputation from
that fallback would otherwise delete the visa rows and lose the applicant's completed marks.

``origin`` is deliberately absent. A client cannot claim a row is a human's or the advisor's decision,
and cannot claim one is its own either: everything a recomputation writes is a ``system`` row, which
is the server's own default for the column. ``status`` and ``completed_at`` are absent for the same
reason on the other side of the rule: those are the applicant's marks, set through the per-row edit
route, and a recomputation that could send them could untick a finished requirement. ``TaskPatch`` is
that route's payload and reads as the mirror image: it carries the status and the dates, and it refuses
``origin``, ``materialKey`` and ``phase``, because editing one row is neither a claim of ownership nor
a change of identity or place.

What this module can decide on its own it decides here — the domain of ``schedule_origin``, and that a
row's dates are optional rather than defaulted. What it cannot is whether a ``materialKey`` or a
``phase`` exists: those are facts about the rows the definition currently holds, so the service checks
them against the tables and answers 422 rather than letting a foreign key turn the mistake into a 500.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.task import ScheduleOrigin, TaskStatus
from app.schemas.common import _camel

# Same wire name as the column, and the empty string rather than None: the uniqueness constraint is
# `(client_id, material_key, program_id)` and a unique constraint does not constrain NULLs, so a
# caller that omitted the key would otherwise be able to insert the same material twice.
DEFAULT_PROGRAM_ID = ""


class TaskIn(BaseModel):
    """One row a recomputation wants to exist, keyed by ``(materialKey, programId)``.

    ``extra="forbid"``, like the profile schemas: a payload that sends ``status`` or ``origin`` has
    misunderstood the rule, and a 422 naming the field says so instead of silently dropping it.

    ``schedule_origin`` is the column's own ``ScheduleOrigin`` rather than a bare string, because the
    three values are the whole domain and a fourth spelling of ``"suggested"`` — the measured case was
    ``"banana"`` — would otherwise be accepted and stored. ``phase`` is a bare string on purpose: its
    domain is the phase keys the definition serves, which are data transcribed from
    ``web/lib/roadmap.ts``, so the service checks the value against ``roadmap_phases`` and rejects an
    unknown one with a 422 instead of an enum going stale here.

    The dates are optional, and their absence is not the same claim as their ``null``: a field the
    payload does not carry leaves the row's date alone, while an explicit ``null`` says the row has no
    date. That is what keeps a recomputation that computed a suggestion date but no deadline from
    silently wiping a deadline the row held.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")

    material_key: str
    program_id: str = DEFAULT_PROGRAM_ID
    phase: str
    suggested_at: date | None = None
    due_at: date | None = None
    schedule_origin: ScheduleOrigin = ScheduleOrigin.SUGGESTED


class TaskPatch(BaseModel):
    """The applicant's own edit of one row: its status and its dates.

    This is the second door onto `roadmap_tasks`, and it is deliberately narrow. ``origin`` is absent
    for the reason ``TaskIn`` omits it — a client cannot claim a row is a human's or the advisor's
    decision — and on this route the absence does more work than that: the service sets ``origin`` to
    ``user`` itself, because the applicant touching a row is what claims it, and a caller that could
    send ``origin`` could claim to be the advisor instead. ``materialKey`` and ``phase`` are absent as
    well: a row's identity and its place in the timeline belong to the recomputation and the
    definition, and a per-row edit is neither. ``extra="forbid"`` turns any of them into a 422 naming
    the field rather than a value silently dropped.

    The dates keep the rule ``TaskIn`` states: a field the payload does not carry leaves the row's date
    alone, while an explicit ``null`` says the row has no date. ``status`` is not nullable, so a
    ``null`` there is refused rather than read as "leave it", and a patch that names none of the three
    fields is refused rather than applied as a no-op. That last rule is not tidiness: every accepted
    edit claims the row for the applicant, a claimed row is one no recomputation may touch again, and
    a caller that submitted an empty patch would therefore freeze the row against the recomputation
    that keeps its dates current.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")

    status: TaskStatus | None = None
    suggested_at: date | None = None
    due_at: date | None = None

    @model_validator(mode="after")
    def _must_state_something(self) -> "TaskPatch":
        """Refuse a payload that states no field, and a status that is not a status.

        ``model_fields_set`` is what separates an omitted field from an explicit ``null`` here, the
        same distinction the service makes for the dates, and the only way to see it: both spellings
        leave the attribute equal to its default, so the value alone cannot tell them apart.
        """
        if not self.model_fields_set:
            raise ValueError(
                "a patch must carry at least one of status, suggestedAt or dueAt: an edit that states "
                "nothing cannot be told apart from an accident, and accepting it would claim the row "
                "for the user without the user having said anything."
            )
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError(
                "status cannot be null: a row always holds pending, in_progress, completed or "
                "skipped, and an omitted status is how 'leave it as it is' is spelled."
            )
        return self


class TaskReplaceRequest(BaseModel):
    """The client's recomputation: which keys are applicable, and the rows it computed for them.

    ``applicable_keys`` may name a key that ``rows`` does not carry — that is the case the design
    section 3.8 defect turns on, and it is how the caller says "still applicable, nothing new to
    write". The other direction is a contradiction rather than an instruction: a key ``rows`` carries
    and ``applicable_keys`` does not is a row the caller computed, which is its own statement that the
    key applies this round. The service rejects that payload with a 422 naming the keys, because
    honouring both statements in one call is what made the outcome depend on whether the row already
    existed — see ``app.services.roadmap_tasks``.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")

    applicable_keys: list[str]
    rows: list[TaskIn] = Field(default_factory=list)


class TaskOut(BaseModel):
    """One row as the applicant's timeline reads it.

    Read straight off the ORM row, so every column a consumer might render is here. ``completedAt``
    stays null unless the row is completed, which is the same distinction ``due_at`` makes: null is
    "not known" or "not done", never a default the applicant did not choose.
    """

    model_config = ConfigDict(
        alias_generator=_camel, populate_by_name=True, from_attributes=True
    )

    id: str
    material_key: str
    program_id: str
    phase: str
    status: str
    suggested_at: date | None = None
    due_at: date | None = None
    schedule_origin: str
    origin: str
    document_id: str | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TaskReplaceResult(BaseModel):
    """What one recomputation did, as the service reports it.

    The caller computed the rows it sent, so the rows are not echoed back; what it cannot compute is
    what happened to the rows it does not own, and `kept` is that number. The four counts are
    disjoint — `created` and `updated` are rows this call wrote, `removed` the rows it deleted, and
    `kept` the existing rows it left exactly as they were, which is every `user`/`agent` row plus
    every `system` row the caller still calls applicable without sending a row for it. An `updated`
    row is not also `kept`: the earlier text here described `kept` as "the rows it does not own" while
    the service returned `len(existing) - removed`, so a single rescheduled row was reported twice.

    `updated` counts the system rows whose dates this round owns, and it counts them whether or not a
    value actually changed: the claim is "this round owns this row", which is true either way.
    """

    created: int
    updated: int
    removed: int
    kept: int
