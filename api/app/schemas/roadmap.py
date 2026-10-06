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
"""

from pydantic import BaseModel, ConfigDict

from app.schemas.common import _camel


class SourceRef(BaseModel):
    """The official page a material's requirement was read from.

    Its three fields are the same three `app.schemas.program.SourceOut` carries, for the same
    reason: `publisher`, `domain` and a verification date are on the row but no consumer renders
    them, and `verified_at` stays null until a human verifies the page, so `status` is what tells
    the reader whether anyone has. The field list is all the two models share, and that is
    deliberate: `SourceOut` is validated from a `sources` row and so sets `from_attributes=True`,
    while this one is built by the roadmap route from the row its material's `source_id` names and
    therefore takes plain keyword arguments.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)

    url: str
    title: str
    status: str


class PhaseOut(BaseModel):
    """One stage of the timeline, as the frontend's `RoadmapPhase` reads it.

    `sort_order` is served as well as used for ordering, because the frontend keeps a phase's
    position as an array index and needs the same value to place a phase it renders on its own.
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
    """The whole definition in one response.

    Both lists are already in the order the timeline reads them, and a consumer renders them as
    they arrive: `phases` from the earliest suggested date to the latest, `materials` grouped by
    that same phase order and ordered within each phase.
    """

    phases: list[PhaseOut]
    materials: list[MaterialOut]
