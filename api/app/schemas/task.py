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
route, and a recomputation that could send them could untick a finished requirement.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import _camel

# Same wire name as the column, and the empty string rather than None: the uniqueness constraint is
# `(client_id, material_key, program_id)` and a unique constraint does not constrain NULLs, so a
# caller that omitted the key would otherwise be able to insert the same material twice.
DEFAULT_PROGRAM_ID = ""


class TaskIn(BaseModel):
    """One row a recomputation wants to exist, keyed by ``(materialKey, programId)``.

    ``extra="forbid"``, like the profile schemas: a payload that sends ``status`` or ``origin`` has
    misunderstood the rule, and a 422 naming the field says so instead of silently dropping it.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")

    material_key: str
    program_id: str = DEFAULT_PROGRAM_ID
    phase: str
    suggested_at: date | None = None
    due_at: date | None = None
    schedule_origin: str = "suggested"


class TaskReplaceRequest(BaseModel):
    """The client's recomputation: which keys are applicable, and the rows it computed for them.

    ``applicable_keys`` may name a key that ``rows`` does not carry — that is the case the design
    section 3.8 defect turns on — and a key that ``rows`` carries but ``applicable_keys`` does not is
    still written, because the row is a fact the client computed.
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
    what happened to the rows it does not own, and `kept` is that number. `updated` counts the system
    rows whose dates moved, and it counts them whether or not a value actually changed: the claim is
    "this round owns this row", which is true either way.
    """

    created: int
    updated: int
    removed: int
    kept: int
