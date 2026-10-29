"""Login, logout, the current account, and account deletion (openspec/changes/account-login)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.deps import COOKIE_NAME, SESSION_COOKIE
from app.models.account import Account
from app.services.accounts import delete_subject
from app.services.auth import (
    AuthError,
    account_for_token,
    client_ip,
    end_session,
    normalize_email,
    request_code,
    verify_code,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

NOT_ENABLED = "登录未开启"


class CodeIn(BaseModel):
    email: str = Field(max_length=320)


class VerifyIn(BaseModel):
    email: str = Field(max_length=320)
    code: str = Field(min_length=1, max_length=12)


class DeleteIn(BaseModel):
    email: str = Field(max_length=320)


def _require_enabled() -> None:
    if not settings.auth_enabled:
        raise HTTPException(404, NOT_ENABLED)


def _email(raw: str) -> str:
    email = normalize_email(raw)
    if email is None:
        raise HTTPException(422, {"code": "invalid_email", "message": "邮箱地址格式不对。"})
    return email


def _refuse(error: AuthError) -> JSONResponse:
    headers = {"Retry-After": str(error.detail["retryAfter"])} if "retryAfter" in error.detail else None
    return JSONResponse({"detail": error.detail}, status_code=error.status, headers=headers)


def _account_out(account: Account | None) -> dict | None:
    if account is None:
        return None
    return {"email": account.email, "createdAt": account.created_at.isoformat() if account.created_at else None}


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me")
def me(request: Request, session: Annotated[Session, Depends(get_session)]) -> dict:
    """Whether login mode is on, and who is logged in. Public, so the interface can decide what to show."""
    if not settings.auth_enabled:
        return {"authEnabled": False, "account": None}
    account = account_for_token(session, request.cookies.get(SESSION_COOKIE))
    return {"authEnabled": True, "account": _account_out(account)}


@router.post("/code")
def send_code(body: CodeIn, request: Request, session: Annotated[Session, Depends(get_session)]):
    _require_enabled()
    email = _email(body.email)
    try:
        request_code(session, email, client_ip(request))
    except AuthError as error:
        return _refuse(error)
    return {"sent": True, "resendAfter": settings.auth_code_resend_seconds}


@router.post("/verify")
def verify(body: VerifyIn, request: Request, session: Annotated[Session, Depends(get_session)]):
    _require_enabled()
    email = _email(body.email)
    try:
        result = verify_code(
            session,
            email,
            body.code,
            anonymous_client_id=request.cookies.get(COOKIE_NAME),
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as error:
        return _refuse(error)
    response = JSONResponse(
        {"account": _account_out(result.account), "created": result.created, "merged": result.merged}
    )
    response.set_cookie(
        SESSION_COOKIE,
        result.token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.auth_session_days * 24 * 3600,
        path="/",
    )
    # The anonymous subject now belongs to the account; after a logout the browser starts afresh.
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.post("/logout")
def logout(request: Request, response: Response, session: Annotated[Session, Depends(get_session)]) -> dict:
    _require_enabled()
    end_session(session, request.cookies.get(SESSION_COOKIE))
    _clear_cookies(response)
    return {"ok": True}


@router.delete("/account")
def delete_account(
    body: DeleteIn, request: Request, response: Response, session: Annotated[Session, Depends(get_session)]
) -> dict:
    """Delete the logged-in account and everything it owns. The body repeats the email as confirmation."""
    _require_enabled()
    account = account_for_token(session, request.cookies.get(SESSION_COOKIE))
    if account is None:
        raise HTTPException(401, "需要登录")
    if normalize_email(body.email) != account.email:
        raise HTTPException(422, {"code": "email_mismatch", "message": "输入的邮箱和当前账号不一致。"})
    result = delete_subject(session, account.client_id)
    _clear_cookies(response)
    return {"deleted": True, **result}
