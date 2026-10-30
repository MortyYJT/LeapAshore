"""Account deletion, the 90-day sweep, and concurrent first logins (openspec/changes/archive/2026-10-30-account-login)."""

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update

from app.cleanup import run as cleanup
from app.config import settings
from app.db import SessionLocal
from app.deps import COOKIE_NAME, SESSION_COOKIE
from app.models.account import Account, AuthSession, LoginCode
from app.models.application import Application
from app.models.client import Client, Profile
from app.models.document import Document, DocumentVersion
from app.models.task import RoadmapTask, TaskEvent
from app.seed import seed_programs
from app.seed_roadmap import seed_roadmap
from app.services import auth as auth_service
from app.services.accounts import new_subject
from app.services.documents import storage_root
from tests.auth_helpers import login, login_mode, new_client, outbox, unique_email  # noqa: F401
from tests.test_documents_api import an_upload
from tests.test_seed import PROGRAM_IDS


@pytest.fixture
def definition(require_db, clear_the_roadmap_definition_after_the_test):
    with SessionLocal() as s:
        seed_programs(s)
        seed_roadmap(s)
        s.commit()


def _blobs() -> set[str]:
    root = storage_root()
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} if root.exists() else set()


# ---------- deletion ----------


def test_deleting_the_account_removes_every_row_and_its_files(login_mode, definition):
    browser = new_client()
    email = login(browser, login_mode)["account"]["email"]
    browser.patch("/api/profile", json={"major": "软件工程"})
    browser.put("/api/applications", json={"rows": [{"programId": PROGRAM_IDS[0], "tier": "稳"}]})
    browser.put(
        "/api/roadmap/tasks",
        json={"applicableKeys": ["aca-transcript"], "rows": [{"materialKey": "aca-transcript", "phase": "academic"}]},
    )
    assert browser.post("/api/documents", files=an_upload(data=b"\x89PNG\r\n\x1a\n" + uuid.uuid4().bytes)).status_code == 201
    assert _blobs()
    with SessionLocal() as s:
        subject = s.scalar(select(Account.client_id).where(Account.email == email))
    token = browser.cookies.get(SESSION_COOKIE)

    refused = browser.request("DELETE", "/api/auth/account", json={"email": "someone@else.test"})
    assert refused.status_code == 422
    deleted = browser.request("DELETE", "/api/auth/account", json={"email": email})
    assert deleted.status_code == 200, deleted.text

    with SessionLocal() as s:
        assert s.get(Client, subject) is None
        for model, column in [
            (Profile, Profile.client_id),
            (Application, Application.client_id),
            (RoadmapTask, RoadmapTask.client_id),
            (TaskEvent, TaskEvent.client_id),
            (Document, Document.client_id),
            (Account, Account.client_id),
        ]:
            assert s.scalar(select(func.count()).select_from(model).where(column == subject)) == 0, model
        assert s.scalar(select(func.count()).select_from(LoginCode).where(LoginCode.email == email)) == 0
        assert s.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.token_hash == auth_service.hash_token(token))) == 0
    assert _blobs() == set()
    stale = new_client()
    stale.cookies.set(SESSION_COOKIE, token)
    assert stale.get("/api/profile").status_code == 401


def test_a_blob_another_subject_shares_survives_deletion(login_mode):
    data = b"\x89PNG\r\n\x1a\n" + uuid.uuid4().bytes
    leaving, staying = new_client(), new_client()
    email = login(leaving, login_mode)["account"]["email"]
    login(staying, login_mode)
    leaving.post("/api/documents", files=an_upload(data=data))
    kept = staying.post("/api/documents", files=an_upload(data=data)).json()["id"]
    assert leaving.request("DELETE", "/api/auth/account", json={"email": email}).status_code == 200
    assert len(_blobs()) == 1
    assert staying.get(f"/api/documents/{kept}/versions/1/file").status_code == 200


def test_deletion_needs_a_session(login_mode):
    assert new_client().request("DELETE", "/api/auth/account", json={"email": "a@b.test"}).status_code == 401


# ---------- the 90-day sweep ----------


def _anonymous(days_ago: int) -> str:
    with SessionLocal() as s:
        cid = str(uuid.uuid4())
        new_subject(s, cid)
        s.execute(update(Client).where(Client.id == cid).values(last_seen_at=datetime.now(UTC) - timedelta(days=days_ago)))
        s.commit()
        return cid


def test_the_sweep_deletes_only_old_unclaimed_subjects(login_mode):
    old, recent = _anonymous(91), _anonymous(10)
    owned_browser = new_client()
    email = login(owned_browser, login_mode)["account"]["email"]
    with SessionLocal() as s:
        owned = s.scalar(select(Account.client_id).where(Account.email == email))
        s.execute(update(Client).where(Client.id == owned).values(last_seen_at=datetime.now(UTC) - timedelta(days=400)))
        s.commit()

    with SessionLocal() as s:
        report = cleanup(s, apply=False)
        assert report["anonymous_subjects"] >= 1
        assert s.get(Client, old) is not None  # a report deletes nothing
        cleanup(s, apply=True)
    with SessionLocal() as s:
        assert s.get(Client, old) is None
        assert s.get(Client, recent) is not None
        assert s.get(Client, owned) is not None


def test_the_sweep_removes_expired_sessions_and_old_codes(login_mode):
    browser = new_client()
    email = login(browser, login_mode)["account"]["email"]
    with SessionLocal() as s:
        s.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)).where(
            AuthSession.account_id == select(Account.id).where(Account.email == email).scalar_subquery()))
        s.execute(update(LoginCode).where(LoginCode.email == email).values(created_at=datetime.now(UTC) - timedelta(days=3)))
        s.commit()
        cleanup(s, apply=True)
        assert s.scalar(select(func.count()).select_from(LoginCode).where(LoginCode.email == email)) == 0
        assert s.scalar(select(func.count()).select_from(AuthSession).join(Account).where(Account.email == email)) == 0


def test_activity_moves_last_seen_at_most_daily(require_db):
    browser = new_client()
    browser.patch("/api/profile", json={"major": "x"})
    cid = browser.cookies.get(COOKIE_NAME)
    week_ago = datetime.now(UTC) - timedelta(days=7)
    with SessionLocal() as s:
        s.execute(update(Client).where(Client.id == cid).values(last_seen_at=week_ago))
        s.commit()
    browser.get("/api/profile")
    with SessionLocal() as s:
        first = s.get(Client, cid).last_seen_at
        assert first > week_ago + timedelta(days=6)
    browser.get("/api/profile")
    with SessionLocal() as s:
        assert s.get(Client, cid).last_seen_at == first


# ---------- concurrency ----------


def test_two_concurrent_first_logins_create_one_account(require_db, monkeypatch):
    """Both logins read "no account" before either inserts, so the insert itself must decide."""
    email = unique_email()
    barrier = threading.Barrier(2, timeout=10)
    original = auth_service._find_account
    calls = threading.local()

    def held_lookup(session, wanted):
        if getattr(calls, "seen", False):
            return original(session, wanted)
        calls.seen = True
        assert original(session, wanted) is None
        barrier.wait()
        return None

    monkeypatch.setattr(auth_service, "_find_account", held_lookup)

    anonymous = []
    with SessionLocal() as s:
        for major in ("甲", "乙"):
            cid = str(uuid.uuid4())
            new_subject(s, cid)
            s.get(Profile, cid).major = major
            anonymous.append(cid)
        s.commit()

    results, errors = [], []

    def run_login(cid):
        try:
            with SessionLocal() as s:
                account, created, merged = auth_service.login_account(s, email, cid)
                s.commit()
                results.append((account.id, account.client_id, created))
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run_login, args=(cid,)) for cid in anonymous]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert errors == []
    assert len({r[0] for r in results}) == 1
    assert sorted(r[2] for r in results) == [False, True]
    with SessionLocal() as s:
        accounts = list(s.scalars(select(Account).where(Account.email == email)))
        assert len(accounts) == 1
        # The loser's anonymous subject was merged into the winner's, not orphaned.
        assert sum(s.get(Client, cid) is not None for cid in anonymous) == 1
        assert s.get(Profile, accounts[0].client_id).major in ("甲", "乙")
