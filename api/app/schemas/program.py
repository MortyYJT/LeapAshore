"""The program catalogue schema, and with it the contract the frontend reads.

`web/lib/programs.ts` is the other half of that contract. Task 8 replaces that hardcoded array
with this endpoint's response, so the keys here have to be the camelCase names `web/lib/types.ts`
already declares for `Program` and `SourceCitation`.
"""

from pydantic import BaseModel, ConfigDict

from app.schemas.common import _camel


class SourceOut(BaseModel):
    """The official page a program's values were read from.

    Carries only what a citation needs to be shown and judged: where it points, what it is called,
    and whether a human has checked it. The frontend's `excerpt` and `verifiedAt` are
    deliberately absent — the excerpt is a manual summary the seed drops, and a verification date
    stays null until someone actually verifies the page.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    url: str
    title: str
    status: str


class ProgramOut(BaseModel):
    """One admission program as the catalogue serves it.

    `minimum_mark` and `non_211_minimum_mark` are annotated `float` per the brief even though the
    Numeric columns hand SQLAlchemy a Decimal; a controller ruling corrects every such annotation
    in one later change, so this file keeps the brief's spelling rather than diverging on its
    own.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    id: str
    name: str
    name_en: str | None = None
    university_name: str
    city: str | None = None
    degree_level: str | None = None
    field: str | None = None
    duration: str | None = None
    minimum_mark: float | None = None
    non_211_minimum_mark: float | None = None
    requires_cognate: bool = False
    english_requirement: str | None = None
    data_status: str
    source: SourceOut
