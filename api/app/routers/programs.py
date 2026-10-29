import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.models.program import Program, University, has_requirement_data
from app.models.source import Source
from app.schemas.program import ProgramOut, SourceOut, deadlines_of

router = APIRouter(prefix="/api/programs", tags=["programs"])

logger = logging.getLogger(__name__)

# Response header naming the programs this request could not serve. The body stays a plain list of
# programs, because every consumer reads it that way, so the defect travels beside it rather than in
# it: a caller that reads only the body still gets the healthy rows, and one that watches the header
# learns that the catalogue is short and which ids are missing.
WITHOUT_SOURCE_HEADER = "X-LeapAshore-Programs-Without-Source"
# How many programs match the filters before paging, so a caller can page through the catalogue.
TOTAL_HEADER = "X-Total-Count"
MAX_PAGE = 100


@router.get("", response_model=list[ProgramOut])
def list_programs(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    field: Annotated[str | None, Query()] = None,
    ids: Annotated[str | None, Query(description="comma-separated program ids")] = None,
    provider: Annotated[str | None, Query(description="university id, or several separated by commas")] = None,
    has_requirements: Annotated[bool | None, Query(alias="has_requirements")] = None,
    q: Annotated[str | None, Query(description="matches the program's names or its school's", max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = MAX_PAGE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProgramOut]:
    """Serve the catalogue. Public data, so no client cookie is issued or required.

    The university and the prerequisites are eager-loaded because every row needs them and a lazy
    load per row would turn one query into six (plus one more per program for its prerequisites).

    `slug` and `university` are built from the program id and the university's display name, in
    that order, because those are the key names `web/lib/types.ts` reads. `prerequisites` is built
    as the program's rows sorted by `sort_order`, the order a reader has to check them in; a
    program with no rows serves `[]`, which is how the frontend knows there is nothing to check.

    A program whose `source_id` does not resolve to a source row is a data defect, not an empty
    citation. The schema makes it unreachable — the column is `NOT NULL` and the foreign key points
    at `sources.id` — so this branch is a backstop for a row a future migration or a manual edit
    could still produce.

    The backstop serves the healthy rows and names the defective ids, instead of failing the whole
    request. Refusing the response was the first version, and one bad row made `GET /api/programs`
    answer 500 for the entire catalogue: five healthy programs became invisible to every applicant
    because a sixth had no provenance. The defect still surfaces — the ids go out in the
    `X-LeapAshore-Programs-Without-Source` header and into an error log — but the applicant keeps
    the catalogue. What does not happen either way is serving a program with no provenance:
    `source: null` is never written, and a defective row is never passed off as sound.

    Two differences from `web/lib/types.ts` cannot be seen from the response alone, so an adapter
    that feeds that type must be told about them rather than discover them by rendering the wrong
    copy:

    - `name` here is the Chinese program name and `nameEn` is the English one, while the
      frontend's `Program.name` is the English name. Mapping `name` to `name` swaps the copy
      rendered at `web/components/HomeView.tsx:79` and `web/components/FlowView.tsx:130`; the
      frontend key that corresponds to this endpoint's `name` is `nameEn`. Neither key is renamed
      here: the database's split is the product's natural shape.
    - `city`, `degreeLevel`, `field`, `duration` and `englishRequirement` are `string | null`
      here and non-nullable `string` in the frontend's type, so the adapter has to narrow them
      instead of assuming they are always present.
    """
    stated = has_requirement_data()
    conditions = []
    if field:
        conditions.append(Program.field == field)
    if ids:
        conditions.append(Program.id.in_([i.strip() for i in ids.split(",") if i.strip()]))
    if provider:
        # Several ids at once: one school can have more than one row (see routers/universities.py).
        conditions.append(Program.university_id.in_([p.strip() for p in provider.split(",") if p.strip()]))
    if has_requirements is not None:
        conditions.append(stated if has_requirements else ~stated)
    if q and q.strip():
        term = f"%{q.strip()}%"
        school = select(University.id).where(or_(University.name.ilike(term), University.name_en.ilike(term)))
        conditions.append(
            or_(Program.name.ilike(term), Program.name_en.ilike(term), Program.university_id.in_(school))
        )

    total = session.scalar(select(func.count()).select_from(Program).where(*conditions))
    response.headers[TOTAL_HEADER] = str(total or 0)
    # Programs with a stated requirement first, so an unfiltered first page is the useful one.
    statement = (
        select(Program)
        .where(*conditions)
        .options(selectinload(Program.university), selectinload(Program.prerequisites),
                 selectinload(Program.deadlines))
        .order_by(stated.desc(), Program.id)
        .limit(limit)
        .offset(offset)
    )
    programs = list(session.execute(statement).scalars())
    # One query for every source on the page, instead of one per program.
    source_ids = {program.source_id for program in programs if program.source_id}
    sources = {row.id: row for row in session.scalars(select(Source).where(Source.id.in_(source_ids)))} if source_ids else {}

    out: list[ProgramOut] = []
    without_source: list[str] = []
    for program in programs:
        source = sources.get(program.source_id)
        if source is None:
            without_source.append(program.id)
            continue
        out.append(
            ProgramOut(
                slug=program.id,
                name=program.name,
                name_en=program.name_en,
                university=program.university.name,
                university_id=program.university_id,
                country=program.university.country,
                city=program.city,
                degree_level=program.degree_level,
                field=program.field,
                duration=program.duration,
                minimum_mark=program.minimum_mark,
                non_211_minimum_mark=program.non_211_minimum_mark,
                requires_cognate=program.requires_cognate,
                prerequisites=[
                    row.label
                    for row in sorted(program.prerequisites, key=lambda row: row.sort_order)
                ],
                english_requirement=program.english_requirement,
                academic_requirement=program.academic_requirement,
                academic_source_url=program.academic_source_url,
                deadlines=deadlines_of(program),
                data_status=program.data_status,
                source=SourceOut(url=source.url, title=source.title, status=source.status),
            )
        )
    if without_source:
        logger.error(
            "programs without a source row, served without them: %s", ", ".join(without_source)
        )
        response.headers[WITHOUT_SOURCE_HEADER] = ", ".join(without_source)
    return out
