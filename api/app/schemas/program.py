"""The program catalogue schema, and with it the contract the frontend reads.

`web/lib/programs.ts` is the other half of that contract. Task 8 replaces that hardcoded array
with this endpoint's response, so the keys here have to be the names `web/lib/types.ts` already
declares for `Program` and `SourceCitation`.

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
wire, while this endpoint's `name` is the Chinese one (`HomeView.tsx:77` and `FlowView.tsx:135`
render the frontend's copy, so a key-for-key adapter would swap it); and the five fields named
above are `string | null` here where the frontend declares a non-nullable `string`. Neither the
keys nor the frontend's declarations are changed by this task — the divergence is only made
visible so the wiring task resolves it deliberately.
"""

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


class ProgramOut(BaseModel):
    """One admission program as the catalogue serves it.

    `slug` and `university` are the frontend's names for the program id and its institution's
    display name; both values are what the database holds, unchanged.

    `prerequisites` carries the program's `program_prerequisites` rows as plain labels in
    `sort_order`, because that is the only thing any consumer does with them: `eligibility.ts`
    joins the list with "、" and tests whether it is empty. A row's `category` and id are read by
    nobody, so they stay off the wire, and an element is a bare string rather than an object.

    `minimum_mark` and `non_211_minimum_mark` are annotated `float` per the brief even though the
    Numeric columns hand SQLAlchemy a Decimal; a controller ruling corrects every such annotation
    in one later change, so this file keeps the brief's spelling rather than diverging on its
    own.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    slug: str
    name: str
    name_en: str | None = None
    university: str
    city: str | None = None
    degree_level: str | None = None
    field: str | None = None
    duration: str | None = None
    minimum_mark: float | None = None
    non_211_minimum_mark: float | None = None
    requires_cognate: bool = False
    prerequisites: list[str] = Field(default_factory=list)
    english_requirement: str | None = None
    data_status: str
    source: SourceOut
