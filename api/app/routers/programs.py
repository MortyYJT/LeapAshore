from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.models.program import Program
from app.models.source import Source
from app.schemas.program import ProgramOut, SourceOut

router = APIRouter(prefix="/api/programs", tags=["programs"])


@router.get("", response_model=list[ProgramOut])
def list_programs(
    session: Annotated[Session, Depends(get_session)],
    field: Annotated[str | None, Query()] = None,
) -> list[ProgramOut]:
    """Serve the catalogue. Public data, so no client cookie is issued or required.

    The university is eager-loaded because every row needs its display name and a lazy load per row
    would turn one query into six.

    A program whose `source_id` points at a row that no longer exists is a data defect, not an
    empty citation, so it makes the request fail loudly instead of serialising `source: null` or
    dropping the program from the list. Both alternatives hide the defect: the first serves a
    program with no provenance, the second silently shrinks the catalogue.
    """
    statement = select(Program).options(selectinload(Program.university)).order_by(Program.id)
    if field:
        statement = statement.where(Program.field == field)

    out: list[ProgramOut] = []
    for program in session.execute(statement).scalars():
        source = session.get(Source, program.source_id) if program.source_id else None
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"program {program.id} has no source row (source_id={program.source_id!r})",
            )
        out.append(
            ProgramOut(
                id=program.id,
                name=program.name,
                name_en=program.name_en,
                university_name=program.university.name,
                city=program.city,
                degree_level=program.degree_level,
                field=program.field,
                duration=program.duration,
                minimum_mark=program.minimum_mark,
                non_211_minimum_mark=program.non_211_minimum_mark,
                requires_cognate=program.requires_cognate,
                english_requirement=program.english_requirement,
                data_status=program.data_status,
                source=SourceOut(url=source.url, title=source.title, status=source.status),
            )
        )
    return out
