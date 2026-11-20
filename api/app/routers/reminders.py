"""Deadline reminder settings and the unsubscribe link (`docs/product/PRD-multi-device.md`, 3.4).

Settings belong to the signed-in account and follow the version rule of every applicant-editable
record: an update states the version it was based on, and a stale one is answered with 409 and the
stored state. The unsubscribe routes are public; what they accept is the signed token from an email.
"""

import json
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_session
from app.deps import LOGIN_REQUIRED, SESSION_COOKIE
from app.models.account import Account
from app.schemas.common import _camel
from app.services import reminders
from app.services.auth import account_for_token
from app.services.versions import StaleVersion, stale_response

router = APIRouter(prefix="/api/reminders", tags=["reminders"])
Database = Annotated[Session, Depends(get_session)]

INVALID_LINK = "这个退订链接无效"
MAX_BODY_BYTES = 2048


def signed_in_account(request: Request, session: Database) -> Account:
    """The account behind the request; 401 without one. Reminders exist only for accounts."""
    account = None
    if settings.auth_enabled:
        account = account_for_token(session, request.cookies.get(SESSION_COOKIE))
    if account is None:
        raise HTTPException(401, LOGIN_REQUIRED)
    return account


Signed = Annotated[Account, Depends(signed_in_account)]


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")
    enabled: StrictBool | None = None
    lead_days: list[StrictInt] | None = Field(None, min_length=1, max_length=reminders.MAX_LEADS)
    base_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def sensible_lead_days(self):
        if "lead_days" in self.model_fields_set:
            days = self.lead_days
            if days is None:
                raise ValueError("提前天数不能为空")
            if len(set(days)) != len(days):
                raise ValueError("提前天数不能重复")
            if any(not reminders.MIN_LEAD <= day <= reminders.MAX_LEAD for day in days):
                raise ValueError(f"提前天数要在 {reminders.MIN_LEAD} 到 {reminders.MAX_LEAD} 之间")
        return self


@router.get("/settings")
def read_settings(account: Signed, session: Database) -> dict:
    return reminders.read_settings(session, account.id)


@router.put("/settings")
def update_settings(payload: SettingsUpdate, account: Signed, session: Database):
    try:
        return reminders.update_settings(
            session, account.id, payload.base_version, enabled=payload.enabled, lead_days=payload.lead_days
        )
    except StaleVersion as stale:
        return stale_response(stale.current)


def _unsubscribe(token: str) -> bool:
    with SessionLocal() as session:
        return reminders.unsubscribe(session, token)


@router.post("/unsubscribe")
async def unsubscribe(request: Request) -> dict:
    """Turn reminders off for the account the token was signed for.

    Two callers: a mail client acting on `List-Unsubscribe-Post` posts a form body to the header's
    URL, token in the query (RFC 8058); the page the email links posts `{"token": ...}`. The answer
    says nothing about the account, and no cookie is read or set.
    """
    token = request.query_params.get("token")
    if token is None:
        try:
            if int(request.headers.get("content-length") or 0) <= MAX_BODY_BYTES:
                body = json.loads(await request.body())
                token = body.get("token") if isinstance(body, dict) else None
        except (ValueError, RecursionError):
            # Not JSON, or JSON nested deeper than the parser goes: either way, no token.
            token = None
    if not isinstance(token, str) or not await run_in_threadpool(_unsubscribe, token):
        raise HTTPException(400, INVALID_LINK)
    return {"unsubscribed": True}


@router.get("/unsubscribe")
def unsubscribe_page(token: str = "") -> RedirectResponse:
    """A GET changes nothing (link scanners fetch every URL in a mail): it leads to the page."""
    return RedirectResponse(f"/reminders/unsubscribe?token={quote(token[:200], safe='.-_')}", status_code=303)
