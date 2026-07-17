from starlette.requests import Request
from fastapi.testclient import TestClient

from app.main import app
from app.middleware import client_ip


client = TestClient(app)


def registered_login(email: str) -> None:
    registered = client.post("/auth/register", json={
        "email": email,
        "password": "demo1234",
        "display_name": "安全测试用户",
        "accepted_terms": True,
    })
    assert registered.status_code == 201
    assert client.post("/auth/verify-email", json={"token": registered.json()["debug_token"]}).status_code == 200
    assert client.post("/auth/login", json={"email": email, "password": "demo1234"}).status_code == 200


def request_with_forwarded_ip(value: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/auth/login",
        "raw_path": b"/auth/login",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", value.encode())],
        "client": ("127.0.0.1", 54321),
        "server": ("testserver", 80),
    })


def test_forwarded_ip_is_ignored_unless_gateway_is_explicitly_trusted(monkeypatch) -> None:
    request = request_with_forwarded_ip("198.51.100.7")
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    assert client_ip(request) == "127.0.0.1"
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    assert client_ip(request) == "198.51.100.7"


def test_cookie_authenticated_mutation_rejects_cross_site_origin(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    registered_login("csrf-guard@offerpilot.cn")
    rejected = client.post(
        "/auth/logout",
        headers={"Origin": "https://attacker.example"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == "请求来源未被允许"


def test_cookie_authenticated_mutation_accepts_configured_origin(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    registered_login("csrf-allowed@offerpilot.cn")
    response = client.post(
        "/auth/logout",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
