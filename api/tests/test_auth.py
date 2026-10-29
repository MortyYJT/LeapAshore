"""Email-code login (openspec/changes/account-login, spec account-auth)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.config import Settings, check_settings, settings
from app.db import SessionLocal
from app.models.account import Account, AuthSession, LoginCode
from app.services import mail
from tests.auth_helpers import (
    SESSION_COOKIE,
    login,
    login_mode,  # noqa: F401 - fixture
    new_client,
    outbox,  # noqa: F401 - fixture
    request_code,
    unique_email,
    unique_ip,
)


def _codes(email: str) -> list[LoginCode]:
    with SessionLocal() as s:
        return list(s.scalars(select(LoginCode).where(LoginCode.email == email).order_by(LoginCode.created_at)))


def _age_codes(email: str, seconds: int) -> None:
    """Move every code of the email `seconds` into the past, as if that much time had passed."""
    with SessionLocal() as s:
        for code in s.scalars(select(LoginCode).where(LoginCode.email == email)):
            code.created_at -= timedelta(seconds=seconds)
            code.expires_at -= timedelta(seconds=seconds)
        s.commit()


# ---------- configuration ----------


def test_production_login_mode_refuses_the_log_backend():
    config = Settings(app_env="production", auth_enabled=True, mail_backend="log")
    with pytest.raises(RuntimeError, match="MAIL_BACKEND=smtp"):
        check_settings(config)


def test_production_login_mode_needs_every_smtp_value():
    config = Settings(app_env="production", auth_enabled=True, mail_backend="smtp", smtp_password="")
    with pytest.raises(RuntimeError, match="SMTP_PASSWORD"):
        check_settings(config)


def test_production_without_login_mode_starts_with_the_log_backend():
    check_settings(Settings(app_env="production", auth_enabled=False, mail_backend="log"))


def test_complete_production_configuration_passes():
    check_settings(
        Settings(
            app_env="production",
            auth_enabled=True,
            mail_backend="smtp",
            smtp_user="noreply@mail.example.test",
            smtp_password="secret",
            mail_from="noreply@mail.example.test",
        )
    )


def test_log_backend_refuses_to_send_in_production(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "mail_backend", "log")
    monkeypatch.setattr(settings, "mail_log_path", tmp_path / "mail.log")
    with pytest.raises(mail.MailError):
        mail.send_login_code("a@example.test", "123456")
    assert not (tmp_path / "mail.log").exists()


def test_log_backend_writes_the_code_to_the_mail_log(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "mail_backend", "log")
    monkeypatch.setattr(settings, "mail_log_path", tmp_path / "mail.log")
    mail.send_login_code("a@example.test", "123456")
    assert "a@example.test 123456" in (tmp_path / "mail.log").read_text()


def test_smtp_backend_sends_over_ssl(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["where"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, message):
            sent["to"] = message["To"]
            sent["body"] = message.get_content()

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(settings, "mail_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_user", "noreply@mail.example.test")
    monkeypatch.setattr(settings, "smtp_password", "pw")
    monkeypatch.setattr(settings, "mail_from", "noreply@mail.example.test")
    mail.send_login_code("a@example.test", "654321")
    assert sent["where"] == ("smtp.qcloudmail.com", 465)
    assert sent["login"] == ("noreply@mail.example.test", "pw")
    assert sent["to"] == "a@example.test"
    assert "654321" in sent["body"]


# ---------- switch off ----------


def test_auth_routes_are_not_found_with_login_mode_off(require_db, outbox, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    client = new_client()
    email = unique_email()
    assert request_code(client, email).status_code == 404
    assert _codes(email) == []
    me = client.get("/api/auth/me").json()
    assert me == {"authEnabled": False, "account": None}


# ---------- sending ----------


def test_first_login_registers_and_sets_an_httponly_session(login_mode):
    client = new_client()
    email = unique_email()
    assert request_code(client, email).status_code == 200
    code = login_mode.last_code(email)
    assert len(code) == 6 and code.isdigit()
    response = client.post("/api/auth/verify", json={"email": email, "code": code})
    assert response.status_code == 200
    assert response.json()["created"] is True
    assert response.json()["account"]["email"] == email
    cookie = response.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in cookie and "httponly" in cookie.lower()
    me = client.get("/api/auth/me").json()
    assert me["authEnabled"] is True and me["account"]["email"] == email


def test_email_is_normalised(login_mode):
    client = new_client()
    email = unique_email()
    assert request_code(client, f"  {email.upper()} ").status_code == 200
    body = client.post("/api/auth/verify", json={"email": email, "code": login_mode.last_code(email)}).json()
    assert body["account"]["email"] == email
    _age_codes(email, 61)
    second = new_client()
    assert login(second, login_mode, email.upper())["created"] is False


@pytest.mark.parametrize("bad", ["", "no-at-sign", "a@b", "a@@b.com", "x" * 250 + "@a.com"])
def test_invalid_email_is_refused(login_mode, bad):
    assert request_code(new_client(), bad).status_code == 422


def test_resend_within_sixty_seconds_is_refused(login_mode):
    client = new_client()
    email = unique_email()
    assert request_code(client, email).status_code == 200
    again = request_code(client, email)
    assert again.status_code == 429
    assert 50 <= again.json()["detail"]["retryAfter"] <= 60
    assert len(login_mode.sent) == 1


def test_resend_after_sixty_seconds_invalidates_the_old_code(login_mode):
    client = new_client()
    email = unique_email()
    request_code(client, email)
    old = login_mode.last_code(email)
    _age_codes(email, 61)
    assert request_code(client, email).status_code == 200
    new = login_mode.last_code(email)
    if old != new:
        refused = client.post("/api/auth/verify", json={"email": email, "code": old})
        assert refused.status_code == 400
    assert client.post("/api/auth/verify", json={"email": email, "code": new}).status_code == 200


def test_daily_cap_per_email(login_mode, monkeypatch):
    monkeypatch.setattr(settings, "auth_codes_per_email_per_day", 3)
    client = new_client()
    email = unique_email()
    for _ in range(3):
        assert request_code(client, email, unique_ip()).status_code == 200
        _age_codes(email, 61)
    capped = request_code(client, email, unique_ip())
    assert capped.status_code == 429
    assert capped.json()["detail"]["code"] == "daily_limit"
    # A day later the window has moved on.
    _age_codes(email, 24 * 3600)
    assert request_code(client, email, unique_ip()).status_code == 200


def test_daily_cap_per_ip(login_mode, monkeypatch):
    monkeypatch.setattr(settings, "auth_codes_per_ip_per_day", 2)
    client = new_client()
    ip = unique_ip()
    assert request_code(client, unique_email(), ip).status_code == 200
    assert request_code(client, unique_email(), ip).status_code == 200
    capped = request_code(client, unique_email(), ip)
    assert capped.status_code == 429
    assert request_code(client, unique_email(), unique_ip()).status_code == 200


def test_forwarded_for_is_ignored_unless_trusted(login_mode, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "")
    email = unique_email()
    request_code(new_client(), email, "203.0.113.9")
    assert _codes(email)[0].ip != "203.0.113.9"


def test_right_most_forwarded_entry_is_the_one_caddy_wrote(login_mode):
    email = unique_email()
    request_code(new_client(), email, "198.51.100.1, 203.0.113.7")
    assert _codes(email)[0].ip == "203.0.113.7"


def test_concurrent_sends_for_one_email_send_one_code(login_mode):
    email = unique_email()

    def send(_):
        return request_code(new_client(), email, unique_ip()).status_code

    with ThreadPoolExecutor(8) as pool:
        statuses = list(pool.map(send, range(8)))
    assert statuses.count(200) == 1
    assert len(_codes(email)) == 1


# ---------- verifying ----------


def test_wrong_code_reports_remaining_attempts(login_mode):
    client = new_client()
    email = unique_email()
    request_code(client, email)
    right = login_mode.last_code(email)
    wrong = "000000" if right != "000000" else "111111"
    response = client.post("/api/auth/verify", json={"email": email, "code": wrong})
    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "wrong_code", "remaining": 4, "message": "验证码不对，还可以再试 4 次。"}


def test_five_wrong_guesses_kill_the_code(login_mode):
    client = new_client()
    email = unique_email()
    request_code(client, email)
    right = login_mode.last_code(email)
    wrong = [f"{n:06d}" for n in range(10) if f"{n:06d}" != right][:5]
    answers = [client.post("/api/auth/verify", json={"email": email, "code": w}).json()["detail"]["code"] for w in wrong]
    assert answers == ["wrong_code"] * 4 + ["too_many_attempts"]
    refused = client.post("/api/auth/verify", json={"email": email, "code": right})
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "code_expired"
    assert client.get("/api/auth/me").json()["account"] is None


def test_concurrent_guesses_are_counted_one_at_a_time(login_mode):
    email = unique_email()
    request_code(new_client(), email)
    right = login_mode.last_code(email)
    guesses = [f"{n:06d}" for n in range(30) if f"{n:06d}" != right][:20]

    def guess(code):
        return new_client().post("/api/auth/verify", json={"email": email, "code": code}).status_code

    with ThreadPoolExecutor(10) as pool:
        statuses = list(pool.map(guess, guesses))
    assert set(statuses) == {400}
    (row,) = _codes(email)
    assert row.attempts == 5
    assert row.invalidated_at is not None
    refused = new_client().post("/api/auth/verify", json={"email": email, "code": right})
    assert refused.status_code == 400


def test_an_expired_code_is_refused(login_mode):
    client = new_client()
    email = unique_email()
    request_code(client, email)
    _age_codes(email, 601)
    response = client.post("/api/auth/verify", json={"email": email, "code": login_mode.last_code(email)})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "code_expired"


def test_a_code_works_once(login_mode):
    email = unique_email()
    request_code(new_client(), email)
    code = login_mode.last_code(email)
    assert new_client().post("/api/auth/verify", json={"email": email, "code": code}).status_code == 200
    again = new_client().post("/api/auth/verify", json={"email": email, "code": code})
    assert again.status_code == 400


def test_verify_without_any_code_is_refused(login_mode):
    response = new_client().post("/api/auth/verify", json={"email": unique_email(), "code": "123456"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "code_expired"


def test_concurrent_verification_of_one_code_logs_in_once(login_mode):
    email = unique_email()
    request_code(new_client(), email)
    code = login_mode.last_code(email)

    def verify(_):
        return new_client().post("/api/auth/verify", json={"email": email, "code": code}).status_code

    with ThreadPoolExecutor(6) as pool:
        statuses = list(pool.map(verify, range(6)))
    assert statuses.count(200) == 1
    with SessionLocal() as s:
        assert s.scalar(select(Account).where(Account.email == email)) is not None


# ---------- sessions ----------


def test_logout_deletes_the_session(login_mode):
    client = new_client()
    login(client, login_mode)
    token = client.cookies.get(SESSION_COOKIE)
    assert client.post("/api/auth/logout").status_code == 200
    stale = new_client()
    stale.cookies.set(SESSION_COOKIE, token)
    assert stale.get("/api/profile").status_code == 401
    assert stale.get("/api/auth/me").json()["account"] is None


def test_the_token_is_stored_hashed(login_mode):
    client = new_client()
    login(client, login_mode)
    token = client.cookies.get(SESSION_COOKIE)
    with SessionLocal() as s:
        assert s.get(AuthSession, token) is None


def test_an_expired_session_is_refused(login_mode):
    client = new_client()
    body = login(client, login_mode)
    with SessionLocal() as s:
        account = s.scalar(select(Account).where(Account.email == body["account"]["email"]))
        s.execute(
            update(AuthSession)
            .where(AuthSession.account_id == account.id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        s.commit()
    assert client.get("/api/profile").status_code == 401


def test_second_login_of_the_same_email_reuses_the_account(login_mode):
    email = unique_email()
    first = login(new_client(), login_mode, email)
    _age_codes(email, 61)
    second = login(new_client(), login_mode, email)
    assert first["created"] is True and second["created"] is False
    with SessionLocal() as s:
        assert len(list(s.scalars(select(Account).where(Account.email == email)))) == 1
