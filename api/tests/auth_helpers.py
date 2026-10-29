"""Shared helpers for the account tests: login mode on, codes captured instead of mailed."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import mail

SESSION_COOKIE = "leapashore_session"
CLIENT_COOKIE = "leapashore_client"


def unique_email() -> str:
    return f"t-{uuid.uuid4().hex[:12]}@example.test"


def unique_ip() -> str:
    n = uuid.uuid4().int
    return f"10.{n % 250}.{(n >> 8) % 250}.{(n >> 16) % 250 + 1}"


class Outbox:
    """Every code the service tried to mail, newest last."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def __call__(self, email: str, code: str) -> None:
        self.sent.append((email, code))

    def last_code(self, email: str) -> str:
        wanted = email.strip().lower()
        return [code for to, code in self.sent if to == wanted][-1]


@pytest.fixture
def outbox(monkeypatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(mail, "send_login_code", box)
    return box


@pytest.fixture
def login_mode(monkeypatch, require_db, outbox):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    return outbox


def request_code(client: TestClient, email: str, ip: str | None = None):
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post("/api/auth/code", json={"email": email}, headers=headers)


def login(client: TestClient, outbox: Outbox, email: str | None = None, ip: str | None = None) -> dict:
    """Request a code and verify it; returns the verify response body."""
    email = email or unique_email()
    ip = ip or unique_ip()
    sent = request_code(client, email, ip)
    assert sent.status_code == 200, sent.text
    verified = client.post(
        "/api/auth/verify",
        json={"email": email, "code": outbox.last_code(email)},
        headers={"X-Forwarded-For": ip},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


def new_client() -> TestClient:
    return TestClient(app)
