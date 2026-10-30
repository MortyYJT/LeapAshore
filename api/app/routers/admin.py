"""Admin endpoints. Admin accounts only: 401 without a session, 403 otherwise and in anonymous mode.

    GET  /api/admin/me
    GET  /api/admin/verification?status=unverified|verified|all&q=&limit=&offset=
    GET  /api/admin/verification/{source_id}
    POST /api/admin/verification/{source_id}/verify  {"contentSha256": "<the version read>"}
    POST /api/admin/verification/{source_id}/revoke
    GET  /api/admin/knowledge-gaps?status=open|recollect_queued|dismissed|all
    GET  /api/admin/knowledge-gaps/{id}
    POST /api/admin/knowledge-gaps/{id}/review  {"decision": "recollect"|"dismiss", "note"?, "schoolKeys"?}

The page verification is openspec source-verification; the knowledge-gap review is openspec
knowledge-gaps D6, D7, whose operations are also `python -m app.knowledge_gaps` on the server (which works
in anonymous mode too). There is no command-line way to verify a page: a confirmation names an admin.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import require_admin
from app.models.account import Account
from app.services import knowledge_gaps as kg
from app.services import source_verification as sv
from app.services.refusals import Refused

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ReviewIn(BaseModel):
    decision: Literal["recollect", "dismiss"]
    note: str | None = Field(default=None, max_length=1000)
    # Collection keys to re-collect instead of the gap's own schools (a school the catalogue lacks).
    school_keys: list[Annotated[str, Field(pattern=kg.SCHOOL_KEY.pattern)]] | None = Field(
        default=None, alias="schoolKeys", max_length=20)


class VerifyIn(BaseModel):
    content_sha256: str = Field(alias="contentSha256", pattern=r"^[0-9a-f]{64}$")


def _refused(error: Refused) -> HTTPException:
    return HTTPException(error.status_code, error.detail)


@router.get("/me")
def me(admin: Annotated[Account, Depends(require_admin)]) -> dict:
    """Whether this request is an admin's; the web app's admin pages answer 404 unless this is 200."""
    return {"email": admin.email, "role": admin.role}


@router.get("/verification")
def list_pages(
    _: Annotated[Account, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    status: Annotated[Literal["unverified", "verified", "all"], Query()] = "unverified",
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    return sv.list_pages(session, status, q, limit, offset)


@router.get("/verification/{source_id}")
def show_page(source_id: str, _: Annotated[Account, Depends(require_admin)],
              session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        return sv.detail(session, source_id)
    except Refused as error:
        raise _refused(error) from None


@router.post("/verification/{source_id}/verify")
def verify_page(source_id: str, body: VerifyIn, admin: Annotated[Account, Depends(require_admin)],
                session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        return sv.verify(session, source_id, body.content_sha256, admin)
    except Refused as error:
        raise _refused(error) from None


@router.post("/verification/{source_id}/revoke")
def revoke_page(source_id: str, admin: Annotated[Account, Depends(require_admin)],
                session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        return sv.revoke(session, source_id, admin)
    except Refused as error:
        raise _refused(error) from None


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
