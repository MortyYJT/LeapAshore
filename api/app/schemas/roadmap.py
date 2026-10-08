"""The roadmap definition schema: the timeline every applicant works through.

`web/lib/roadmap.ts` is the other half of this contract. Until the annotation stage replaces both
with reviewed data, the seed transcribes that file into the two roadmap tables and this module
serves them back under the frontend's own key names, so a consumer can drop the hardcoded constants
without renaming anything it reads. The transcription's field mapping is recorded in
`app/seed_roadmap.py`; what matters here is that the wire keeps it: `offset_days` leaves as
`offsetDays`, `sort_order` as `sortOrder`, `applies_to` as `appliesTo`, and the phase key of a
material stays `phase`.

A material's `source` is `None` when it has none, and that is a fact rather than a gap: six of the
seven phases are placeholder copy with no official page behind them yet, and serving an invented or
empty citation for them would claim provenance nobody established. Only the authored visa materials
cite a page, and they carry it.

`detail` and a phase's `subtitle` follow their columns and stay nullable. `NULL` means "this
definition does not carry that copy", which is not the same as an empty string, and collapsing the
two would turn an unknown into a claim.

`tasks` is the one part of the response that is not shared configuration. It is the caller's own
rows, defined in `app/schemas/task.py`, and it is why the route that serves this model resolves a
subject cookie.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import _camel
from app.schemas.task import TaskOut


class SourceRef(BaseModel):
    """The official page a material's requirement was read from.

    Its three fields are the same three `app.schemas.program.SourceOut` carries, for the same
    reason: `publisher`, `domain` and a verification date are on the row but no consumer renders
    them, and `verified_at` stays null until a human verifies the page, so `status` is what tells
    the reader whether anyone has. Both models are built the same way — from the row their route
    just read, by plain keyword arguments — and the field list is all they share: the one real
    difference is that `SourceOut` declares `from_attributes=True` and this model does not, so a
    `sources` row can be validated into a `SourceOut` directly while a `SourceRef` is always
    constructed explicitly.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)

    # Nullable, and null rather than an empty string when the row behind the citation cannot be read.
    # Every writer of a citation requires the `sources` row to exist — `programs.source_id` and
    # `review_criteria.source_id` are both NOT NULL with RESTRICT — so an absent one means a caller
    # joined something it should not have, and the honest answer to "which page said this" is then
    # "none readable", not a url-shaped empty string.
    url: str | None = None
    title: str | None = None
    status: str | None = None


class PhaseOut(BaseModel):
    """One stage of the timeline, as the frontend's `RoadmapPhase` reads it.

    `sort_order` is served as well as used for ordering, and no consumer reads it: the frontend
    keeps a phase's position as its index in the returned array, which is why the list arrives
    ordered rather than being sorted again on the other side. It stays on the wire because it is the
    value the route ordered by, and `MaterialOut` serves its own `sort_order` on the same terms. The
    comment that used to justify it — that the frontend needed the number "to place a phase it
    renders on its own" — named a consumer that does not exist; nothing renders a phase on its own.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    key: str
    title: str
    subtitle: str | None = None
    offset_days: int
    sort_order: int


class MaterialOut(BaseModel):
    """One thing to prepare, as the frontend's `MaterialItem` reads it.

    `applies_to` is the filter the frontend already applies: `all`, `portfolio` or `research`. It is
    served for every material, including the ones a given applicant never sees, because the caller
    is the one that knows the profile.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    key: str
    phase: str
    title: str
    detail: str | None = None
    applies_to: str
    sort_order: int
    source: SourceRef | None = None


class RoadmapDefinition(BaseModel):
    """The whole definition in one response, plus the caller's own rows.

    Both definition lists are already in the order the timeline reads them, and a consumer renders
    them as they arrive: `phases` from the earliest suggested date to the latest, `materials` grouped
    by that same phase order and ordered within each phase.

    `tasks` carries the caller's rows, which are the opposite kind of data to the other two: the
    definition is shared configuration, identical for every caller, while a task row belongs to one
    subject and is the reason this route now reads the subject cookie. The field defaults to an empty
    list so that a caller which only has a definition — the tests that seed one and read it back, or
    any consumer written before this batch — gets the same shape without supplying anything.
    """

    phases: list[PhaseOut]
    materials: list[MaterialOut]
    tasks: list[TaskOut] = Field(default_factory=list)
