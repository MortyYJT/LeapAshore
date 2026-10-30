"""Admin endpoints: the knowledge-gap review (openspec knowledge-gaps D6, D7). Admin accounts only.

    GET  /api/admin/knowledge-gaps?status=open|recollect_queued|dismissed|all
    GET  /api/admin/knowledge-gaps/{id}
    POST /api/admin/knowledge-gaps/{id}/review  {"decision": "recollect"|"dismiss", "note"?, "schoolKeys"?}

The same operations are `python -m app.knowledge_gaps` on the server, which also works in anonymous mode.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import require_admin
from app.models.account import Account
from app.services import knowledge_gaps as kg
from app.services.refusals import Refused

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ReviewIn(BaseModel):
    decision: Literal["recollect", "dismiss"]
    note: str | None = Field(default=None, max_length=1000)
    # Collection keys to re-collect instead of the gap's own schools (a school the catalogue lacks).
    school_keys: list[Annotated[str, Field(pattern=kg.SCHOOL_KEY.pattern)]] | None = Field(
        default=None, alias="schoolKeys", max_length=20)


def _refused(error: Refused) -> HTTPException:
    return HTTPException(error.status_code, error.detail)


@router.get("/knowledge-gaps")
def list_gaps(
    _: Annotated[Account, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    status: Annotated[Literal["open", "recollect_queued", "dismissed", "all"], Query()] = "open",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    return {"gaps": kg.list_gaps(session, status, limit)}


@router.get("/knowledge-gaps/{gap_id}")
def show_gap(gap_id: str, _: Annotated[Account, Depends(require_admin)],
             session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        return kg.show_gap(session, gap_id)
    except Refused as error:
        raise _refused(error) from None


@router.post("/knowledge-gaps/{gap_id}/review")
def review_gap(gap_id: str, body: ReviewIn, admin: Annotated[Account, Depends(require_admin)],
               session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        return kg.review(session, gap_id, body.decision, reviewer=admin.id, note=body.note,
                         school_keys=body.school_keys)
    except Refused as error:
        raise _refused(error) from None
