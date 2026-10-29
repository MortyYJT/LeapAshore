"""The schools the catalogue holds, with how many programs each has.

The school library lists 287 schools from its own file and joins them to these rows by name, so a
school page can read that school's programs. One school can have several rows: CRICOS lists some
universities under more than one provider code, and the requirement importer may have created a row for
a school whose site refused collection. The library groups rows by name and reads their programs with
one `provider=<id>,<id>` request.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.program import Program, University
from app.schemas.common import _camel

router = APIRouter(prefix="/api/universities", tags=["universities"])


class UniversityOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)

    id: str
    name: str
    name_en: str | None = None
    country: str
    program_count: int
    with_requirements_count: int


@router.get("", response_model=list[UniversityOut])
def list_universities(session: Annotated[Session, Depends(get_session)]) -> list[UniversityOut]:
    """Public data, like the program catalogue: no client cookie is read or issued."""
    stated = or_(Program.minimum_mark.is_not(None), Program.english_requirement.is_not(None))
    counts = (
        select(
            Program.university_id,
            func.count().label("total"),
            func.count().filter(stated).label("stated"),
        )
        .group_by(Program.university_id)
        .subquery()
    )
    rows = session.execute(
        select(University, counts.c.total, counts.c.stated)
        .outerjoin(counts, counts.c.university_id == University.id)
        .order_by(University.id)
    )
    return [
        UniversityOut(
            id=university.id,
            name=university.name,
            name_en=university.name_en,
            country=university.country,
            program_count=total or 0,
            with_requirements_count=stated or 0,
        )
        for university, total, stated in rows
    ]
