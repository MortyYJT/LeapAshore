"""The school-choice portfolio schema: what one choice looks like going in and coming out.

`applications` holds the applicant's 冲 / 稳 / 保 portfolio, one row per program, and this module
carries both directions of it. A row read out of the database leaves as ``ApplicationOut``, with the
program it names projected alongside it because that is what the portfolio lists render; a whole
portfolio arrives as ``ApplicationReplaceRequest``, which replaces whatever the subject held.

The two vocabularies these payloads carry are the model's own — ``ApplicationTier`` and
``ApplicationStatus`` — and they are imported rather than restated. ``ApplicationOrigin``, the third,
has no field here on purpose: the server writes ``user`` on everything the route stores, so the field
is refused rather than accepted and quietly ignored. The columns stay plain strings (the model says
why), so this is the layer that refuses a band or a status the model never defined, and a second
spelling of 冲 elsewhere in the codebase would be a second answer to what a portfolio row may hold.

What this module can decide on its own it decides here: the membership of those two vocabularies, and
that an omitted field means "leave it" while an explicit ``null`` means "clear it" for the two
deadline fields — with ``isPrimary`` the one exception, because the first choice belongs to the
portfolio the replacement states rather than to the row it is written on. What it cannot is whether a
``programId`` exists — that is a fact about the rows the catalogue currently holds, so
``app.services.applications`` checks it against ``programs`` and answers 422 rather than letting a
foreign key turn the mistake into a 500. The two ways one payload can break the table's own
constraints — the same program named twice, and two first choices — are checked there as well, and for
the same reason: they are facts about the whole list, and the interface ``replace_applications`` is
callable without a schema in front of it.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.application import ApplicationStatus, ApplicationTier
from app.schemas.common import _camel


class ApplicationIn(BaseModel):
    """One program the applicant wants in their portfolio, as the replacement states it.

    ``extra="forbid"``, like the profile and task schemas: a payload that sends ``origin``, ``id`` or
    ``clientId`` has misunderstood the route, and a 422 naming the field says so instead of a value
    silently dropped. ``origin`` matters most of the three — the server writes ``user`` on everything
    this route stores, and a client that could send the field could claim the advisor had chosen a
    row the client chose itself.

    ``tier`` is the model's ``ApplicationTier`` and is required: the column has no default, because a
    choice with no band is not a choice with an unknown one, and the applicant is the only one who
    knows whether a program is a reach, a match or a safety. ``status`` is the model's
    ``ApplicationStatus`` and is not: a row that does not say where it has got to is *considering*,
    which is the column's own default. A ``null`` status is refused rather than read as "leave it",
    because a status is not something that can be cleared.

    The two deadline fields are optional and their absence is not the same claim as their ``null``: a
    field the payload does not carry leaves the row's value alone, while an explicit ``null`` says the
    row has none. They move independently, each by its own rule. That is what keeps a replacement that
    states a band but not a deadline from silently wiping a deadline the applicant entered, and an
    official deadline nobody has looked up stays ``null`` rather than becoming a date this API made up.

    ``is_primary`` defaults to ``False`` and a replacement states it for every row: a payload that
    lists the portfolio says which one of those rows is the first choice, so a row it does not mark is
    not one, and the stored flag is deliberately not left alone. Reading the omission as "leave it"
    would let a caller move its first choice to another program while the stored row kept the flag —
    two first choices in one portfolio, which the partial index refuses and which is the whole reason
    the replacement states the flag rather than patching it.

    ``needs_review`` does follow the omission rule, and its default is the column's: a program the
    applicant added by hand is flagged by the caller that knows the system could not tier it, and a
    payload that says nothing about the flag leaves the row's own answer alone.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")

    program_id: str
    tier: ApplicationTier
    status: ApplicationStatus | None = None
    is_primary: bool = False
    official_deadline: date | None = None
    deadline_source_url: str | None = None
    needs_review: bool = False

    @model_validator(mode="after")
    def _a_status_cannot_be_cleared(self) -> "ApplicationIn":
        """Refuse a status of ``null`` while keeping an omitted status meaning "as it is".

        ``model_fields_set`` is what separates an omitted field from an explicit ``null``: both leave
        the attribute equal to its default, so the value alone cannot tell them apart. A row always
        holds one of the model's three statuses, so an explicit ``null`` is a request to store nothing
        rather than a value, and it is answered with a message instead of being read as silence.
        """
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError(
                "status cannot be null: a portfolio row always holds considering, applying or "
                "excluded, and an omitted status is how 'leave it as it is' is spelled."
            )
        return self


class ApplicationReplaceRequest(BaseModel):
    """The applicant's whole portfolio, as one statement.

    The rows are the entire portfolio rather than a patch: a program the payload no longer names is
    gone from it, which is what makes the confirmation flow — the applicant ticks the programs they
    want and submits the list — expressible as one call. An empty ``rows`` is therefore a real
    statement that the portfolio holds nothing, and it empties it.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")

    rows: list[ApplicationIn] = Field(default_factory=list)


class ProgramRef(BaseModel):
    """The program a portfolio row names, projected to what the portfolio lists render.

    This is a projection rather than the catalogue row `app.schemas.program.ProgramOut` serves, and
    the difference is deliberate: the two portfolio lists draw the institution and the program name
    (`HomeView.tsx:77` and `FlowView.tsx:135`) and nothing else from the program, so a portfolio read
    does not need to carry marks, prerequisites and a citation per row. The full record stays on
    `/api/programs`, which is where the picker reads it.

    ``name`` is the Chinese program name and ``name_en`` the English one, the same split
    `app.schemas.program` records: the frontend's ``Program.name`` is the English name, so the key a
    portfolio view wants is ``nameEn``. Both are served so the mapping is the consumer's to make
    rather than one this schema makes silently.

    A row whose program cannot be read is served with ``program: null`` instead of being dropped or
    filled in with invented copy — see ``ApplicationOut.program``.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    slug: str
    name: str
    name_en: str | None = None
    university: str
    city: str | None = None
    degree_level: str | None = None
    data_status: str


class ApplicationOut(BaseModel):
    """One portfolio row as the applicant's own read serves it.

    Read off the ORM row, so every column the frontend might render is here, plus the program the row
    names. ``official_deadline`` and ``deadline_source_url`` stay ``null`` until somebody looks a
    deadline up: null is "not known", never a default the applicant did not choose.

    ``program`` is ``None`` only when the program row the portfolio row names cannot be read. The
    foreign key makes that unreachable — a program cannot be deleted while a portfolio names it — so
    it is a backstop for a row a future migration or a manual edit could still produce, and the
    applicant's own choice is served either way: dropping the row would hide a decision the applicant
    made because of a defect in the catalogue, and inventing a placeholder would pass a guess off as
    the program. The frontend already renders a portfolio row it cannot resolve by its slug.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    id: str
    program_id: str
    tier: str
    status: str
    is_primary: bool
    official_deadline: date | None = None
    deadline_source_url: str | None = None
    needs_review: bool
    origin: str
    program: ProgramRef | None = None
    created_at: datetime
    updated_at: datetime


class ApplicationReplaceResult(BaseModel):
    """What one replacement did, as the service reports it.

    The caller sent the rows, so the rows are not echoed back; what it cannot compute from its own
    payload is how the write landed against what was already stored, and the four counts are that.
    They are disjoint and each means one thing: ``created`` is a program the applicant did not hold,
    ``updated`` is a row this call moved, ``kept`` is a row the payload restated with nothing changed,
    and ``removed`` is a program the payload no longer names. ``updated`` and ``kept`` together are
    the rows that were already there, so the writer and the reader can each check the count they care
    about rather than trusting that the call did something.
    """

    created: int
    updated: int
    kept: int
    removed: int
