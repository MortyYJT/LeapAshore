"""The program catalogue schema, and with it the contract the frontend reads.

The frontend reads this endpoint's response directly, so the keys here have to be the names
`web/lib/types.ts` declares for `Program` and `SourceCitation`.

Two names deliberately do not go through the camelCase alias generator, because their snake_case
form would not become the key the frontend reads: `id` would stay `id` where the frontend reads
`slug`, and `university_name` would become `universityName` where the frontend reads `university`.
Those two fields are therefore named after the wire key itself.

Nullable fields follow the columns, not the frontend's declarations. `city`, `degree_level`,
`field`, `duration` and `english_requirement` may be `NULL` in `programs`, where `NULL` means "this
catalogue does not know yet". Serving an empty string in its place would turn an unknown into a
claim, which is the failure this product exists to avoid, so the nullability stays visible on the
wire and the consumer has to handle it.

Two differences from `web/lib/types.ts` are recorded here because the catalogue-wiring task reads
this file: the frontend's `Program.name` is the English program name, which is `name_en` on this
wire, while this endpoint's `name` is the Chinese one (`HomeView.tsx:79` and `FlowView.tsx:130`
render the frontend's copy, so a key-for-key adapter would swap it); and the five fields named
above are `string | null` here where the frontend declares a non-nullable `string`. Neither the
keys nor the frontend's declarations are changed by this task — the divergence is only made
visible so the wiring task resolves it deliberately.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import _camel


class SourceOut(BaseModel):
    """The official page a program's values were read from.

    Carries only what a citation needs to be shown and judged: where it points, what it is called,
    and whether a human has checked it. The frontend's `excerpt`, `id` and `verifiedAt` are
    deliberately absent — no product code reads them, the excerpt is a manual summary the seed
    drops, a row id is internal, and a verification date stays null until someone actually
    verifies the page.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    url: str
    title: str
    status: str


class DeadlineOut(BaseModel):
    """One collected application deadline: the round's label, the date, and the page that states it.

    Served whether or not it has passed; the reader decides against today (openspec requirement-dates
    D4), so a cached response cannot carry a stale "still open".
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)

    label: str | None = None
    date: date
    source_url: str


def deadlines_of(program) -> list[DeadlineOut]:
    return [DeadlineOut(label=row.label, date=row.deadline, source_url=row.source_url)
            for row in sorted(program.deadlines, key=lambda row: row.sort_order)]


class MaterialOut(BaseModel):
    """One application material the program's page asks for: a type from the fixed list, the count when
    the page states one, the collector's note, the sentence it was read from and the page that is on.

    `key` is the name an applicant's tick is stored under.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)

    key: str
    type: str
    count: int | None = None
    note: str | None = None
    quote: str
    source_url: str


class MaterialsOut(BaseModel):
    """What the program's page asks an applicant to send, as collected.

    Served only for a program whose page has been read for materials; `ProgramOut.materials` is `null`
    otherwise. `items: []` is a page that was read and lists none, which is a different statement.
    Every quote passed the verbatim check against the page's snapshot; nobody verified it by hand.
    """

    items: list[MaterialOut] = Field(default_factory=list)


def materials_of(program) -> MaterialsOut | None:
    if program.materials_snapshot_sha256 is None:
        return None
    return MaterialsOut(items=[
        MaterialOut(key=row.key, type=row.type, count=row.count, note=row.note, quote=row.quote,
                    source_url=row.source_url)
        for row in sorted(program.materials, key=lambda row: row.sort_order)
    ])


class ProgramOut(BaseModel):
    """One admission program as the catalogue serves it.

    `slug` and `university` are the frontend's names for the program id and its institution's
    display name; both values are what the database holds, unchanged.

    `prerequisites` carries the program's `program_prerequisites` rows as plain labels in
    `sort_order`, because that is the only thing any consumer does with them: `eligibility.ts`
    joins the list with "、" and tests whether it is empty. A row's `category` and id are read by
    nobody, so they stay off the wire, and an element is a bare string rather than an object.

    `minimum_mark` and `non_211_minimum_mark` are `float` here because this layer is the wire, and
    JSON has one number type: the ORM attributes are `Decimal` (`Numeric` reads back as `Decimal`,
    and the models say so), and Pydantic serialises that `Decimal` to a JSON number on the way out.
    An earlier version of this docstring deferred the correction of the model annotations to a later
    change; that change has landed, so the note is gone.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    slug: str
    name: str
    name_en: str | None = None
    university: str
    # The school's id and country, so a program row can link to its school and be grouped by country.
    university_id: str
    country: str
    city: str | None = None
    degree_level: str | None = None
    field: str | None = None
    duration: str | None = None
    minimum_mark: float | None = None
    non_211_minimum_mark: float | None = None
    requires_cognate: bool = False
    prerequisites: list[str] = Field(default_factory=list)
    english_requirement: str | None = None
    # The collector's summary of the academic requirement (English), NULL when not collected.
    academic_requirement: str | None = None
    # The page the academic requirement was read from, which can be a shared admissions page.
    academic_source_url: str | None = None
    deadlines: list[DeadlineOut] = Field(default_factory=list)
    # `null`: the page has not been read for materials. An object: it has, and `items` is what it asks for.
    materials: MaterialsOut | None = None
    data_status: str
    source: SourceOut
