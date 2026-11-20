"""Personal application management; catalogue selection APIs keep their existing contract.

The rules are in `app.services.application_records`, which the advisor's confirmed changes go through
as well; these routes turn its refusals into 404, 409 and 422.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_subject
from app.services import application_records as records
from app.services.application_records import RecordCreate, RecordPatch
from app.services.versions import StaleVersion, stale_response

router = APIRouter(prefix="/api/application-records", tags=["application records"])
Subject = Annotated[str, Depends(get_subject)]
Database = Annotated[Session, Depends(get_session)]


@router.get("")
def read_records(client_id: Subject, session: Database):
    return records.read_records(client_id, session)


@router.post("", status_code=201)
def create_record(
    payload: RecordCreate,
    client_id: Subject,
    session: Database,
    response: Response,
    idempotency_key: Annotated[
        str, Header(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    """Create a manual application once per `Idempotency-Key`: 201 for the request that created it,
    200 with the stored record for a replay, which writes nothing."""
    try:
        record, created = records.create_record(session, client_id, payload, idempotency_key)
    except records.InvalidRecord as exc:
        raise HTTPException(422, str(exc)) from exc
    if not created:
        response.status_code = 200
    return record


@router.patch("/{key}")
def update_record(
    key: str, payload: RecordPatch, client_id: Subject, session: Database
):
    try:
        return records.update_record(session, client_id, key, payload)
    except records.RecordNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except StaleVersion as exc:
        return stale_response(exc.current)
    except records.InvalidRecord as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/{key}", status_code=204)
def delete_record(
    key: str,
    client_id: Subject,
    session: Database,
    base_version: Annotated[str, Query(alias="baseVersion", min_length=1, max_length=64)],
):
    """Remove a record the caller has seen in its current state; a stale version is a 409."""
    try:
        records.delete_record(session, client_id, key, base_version)
    except records.RecordNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except StaleVersion as exc:
        return stale_response(exc.current)
    return Response(status_code=204)
