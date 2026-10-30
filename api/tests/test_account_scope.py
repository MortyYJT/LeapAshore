"""Login mode: which routes need a session, and one account never reaches another's rows.

openspec/changes/archive/2026-10-30-account-login, spec account-data-scope.
"""

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.deps import COOKIE_NAME
from app.models.account import Account
from app.models.client import Client
from app.routers import advisor
from app.seed import seed_programs
from app.services.documents import MIME_PNG
from tests.auth_helpers import login, login_mode, new_client, outbox  # noqa: F401 - fixtures
from tests.test_documents_api import an_upload
from tests.test_seed import PROGRAM_IDS


@pytest.fixture
def programs(require_db):
    with SessionLocal() as s:
        seed_programs(s)
        s.commit()


def _client_count() -> int:
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(Client))


def _subject_of(email: str) -> str:
    with SessionLocal() as s:
        return s.scalar(select(Account.client_id).where(Account.email == email))


PRIVATE = [
    ("GET", "/api/profile", None),
    ("PATCH", "/api/profile", {"major": "软件工程"}),
    ("GET", "/api/applications", None),
    ("PUT", "/api/applications", {"rows": []}),
    ("GET", "/api/documents", None),
    ("PUT", "/api/roadmap/tasks", {"applicableKeys": [], "rows": []}),
    ("POST", "/api/advisor/chat", {"conversationId": "c1", "message": "你好"}),
    ("POST", "/api/advisor/confirm", {"conversationId": "c1", "approved": True}),
]


@pytest.mark.parametrize(("method", "path", "body"), PRIVATE)
def test_private_routes_need_a_session_and_write_nothing(login_mode, method, path, body):
    before = _client_count()
    response = new_client().request(method, path, json=body)
    assert response.status_code == 401
    assert response.json()["detail"] == "需要登录"
    assert COOKIE_NAME not in response.headers.get("set-cookie", "")
    assert _client_count() == before


def test_upload_needs_a_session(login_mode):
    assert new_client().post("/api/documents", files=an_upload()).status_code == 401


@pytest.mark.parametrize(
    "path", ["/api/programs", "/api/universities", "/api/review-criteria", "/api/advisor/status", "/api/health"]
)
def test_catalogue_routes_stay_public(login_mode, path):
    assert new_client().get(path).status_code == 200


def test_the_roadmap_definition_is_public_without_tasks(login_mode):
    response = new_client().get("/api/roadmap")
    assert response.status_code == 200
    assert response.json()["tasks"] == []


def test_an_old_anonymous_cookie_grants_nothing_in_login_mode(login_mode, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "auth_enabled", False)
    browser = new_client()
    assert browser.patch("/api/profile", json={"major": "金融"}).status_code == 200
    monkeypatch.setattr(settings, "auth_enabled", True)
    assert browser.get("/api/profile").status_code == 401


def test_account_a_cannot_reach_account_b(login_mode, programs):
    a, b = new_client(), new_client()
    login(a, login_mode)
    login(b, login_mode)

    assert b.patch("/api/profile", json={"major": "B 的专业"}).status_code == 200
    assert b.put("/api/applications", json={"rows": [{"programId": PROGRAM_IDS[0], "tier": "稳"}]}).status_code == 200
    b_doc = b.post("/api/documents", files=an_upload()).json()["id"]

    assert a.get("/api/profile").json()["major"] in (None, "")
    assert a.get("/api/applications").json() == []
    assert a.get("/api/documents").json() == []
    assert a.get(f"/api/documents/{b_doc}").status_code == 404
    assert a.get(f"/api/documents/{b_doc}/versions/1/file").status_code == 404

    # A's writes land in A's subject and leave B's rows as they were.
    assert a.put("/api/applications", json={"rows": [{"programId": PROGRAM_IDS[1], "tier": "冲"}]}).status_code == 200
    assert [r["programId"] for r in b.get("/api/applications").json()] == [PROGRAM_IDS[0]]
    assert b.get("/api/profile").json()["major"] == "B 的专业"
    assert [d["id"] for d in b.get("/api/documents").json()] == [b_doc]


def test_advisor_runs_with_the_session_subject_only(login_mode, monkeypatch):
    seen = []

    async def fake_stream(graph_input, config):
        seen.append(config["configurable"])
        yield advisor._event({"type": "done"})

    monkeypatch.setattr(advisor, "_stream", fake_stream)
    a, b = new_client(), new_client()
    email_a = login(a, login_mode)["account"]["email"]
    login(b, login_mode)
    # Carrying someone's anonymous cookie as well changes nothing.
    a.cookies.set(COOKIE_NAME, _subject_of(login(new_client(), login_mode)["account"]["email"]))
    response = a.post("/api/advisor/chat", json={"conversationId": "c1", "message": "我的背景是什么"})
    assert response.status_code == 200
    assert COOKIE_NAME not in response.headers.get("set-cookie", "")
    assert seen == [{"thread_id": f"{_subject_of(email_a)}:c1", "client_id": _subject_of(email_a)}]


def test_advisor_tools_read_the_configured_subject(login_mode):
    from app.agent.tools import get_my_profile

    a, b = new_client(), new_client()
    email_a = login(a, login_mode)["account"]["email"]
    email_b = login(b, login_mode)["account"]["email"]
    a.patch("/api/profile", json={"major": "A 的专业"})
    b.patch("/api/profile", json={"major": "B 的专业"})
    out = get_my_profile.invoke({}, config={"configurable": {"client_id": _subject_of(email_a)}})
    assert "A 的专业" in out and "B 的专业" not in out
    assert "B 的专业" in get_my_profile.invoke({}, config={"configurable": {"client_id": _subject_of(email_b)}})


def test_refusals_keep_their_status_in_login_mode(login_mode, programs):
    """The refusal paths used to copy the anonymous cookie header, which login mode never sets."""
    client = new_client()
    login(client, login_mode)
    twice = [{"programId": PROGRAM_IDS[0], "tier": "稳"}, {"programId": PROGRAM_IDS[0], "tier": "冲"}]
    assert client.put("/api/applications", json={"rows": twice}).status_code == 422
    bad = client.post("/api/documents", files=an_upload("notes.txt", b"plain text, not a document", "text/plain"))
    assert 400 <= bad.status_code < 500, bad.status_code
