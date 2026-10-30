"""Anonymous data at first login (openspec/changes/archive/2026-10-30-account-login, D7; spec anonymous-merge)."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.deps import COOKIE_NAME
from app.models.account import Account
from app.models.application import Application
from app.models.client import Client, Profile
from app.models.document import Document
from app.models.task import RoadmapTask, TaskEvent
from app.seed import seed_programs
from app.seed_roadmap import seed_roadmap
from app.services.accounts import merge_subject, new_subject
from tests.auth_helpers import login, login_mode, new_client, outbox, unique_email  # noqa: F401
from tests.test_auth import _age_codes
from tests.test_documents_api import an_upload
from tests.test_seed import PROGRAM_IDS

P, Q, R = PROGRAM_IDS[:3]
MATERIAL, OTHER = "aca-transcript", "aca-scale"


@pytest.fixture(autouse=True)
def definition(require_db, clear_the_roadmap_definition_after_the_test):
    with SessionLocal() as s:
        seed_programs(s)
        seed_roadmap(s)
        s.commit()


def _subject(s, **profile) -> str:
    cid = str(uuid.uuid4())
    new_subject(s, cid)
    for k, v in profile.items():
        setattr(s.get(Profile, cid), k, v)
    s.flush()
    return cid


def _app(s, cid, program, tier, primary=False):
    row = Application(id=str(uuid.uuid4()), client_id=cid, program_id=program, tier=tier, is_primary=primary)
    s.add(row)
    s.flush()
    return row


def _task(s, cid, material, program=""):
    row = RoadmapTask(id=str(uuid.uuid4()), client_id=cid, material_key=material, program_id=program, phase="academic")
    s.add(row)
    s.flush()
    return row


def _doc(s, cid, task_id=None):
    row = Document(id=str(uuid.uuid4()), client_id=cid, title="成绩单", task_id=task_id)
    s.add(row)
    s.flush()
    return row


def test_an_account_profile_with_answers_is_kept_whole():
    with SessionLocal() as s:
        target = _subject(s, major="软件工程", gpa_score=Decimal("85"), gpa_scale=Decimal("100"))
        source = _subject(s, major="金融", gpa_score=Decimal("3.6"), gpa_scale=Decimal("4"), intake="2027 S1")
        merge_subject(s, source, target)
        kept = s.get(Profile, target)
        assert (kept.major, kept.gpa_score, kept.gpa_scale, kept.intake) == ("软件工程", Decimal("85"), Decimal("100"), None)
        assert s.get(Client, source) is None
        s.rollback()


def test_an_empty_account_profile_takes_the_anonymous_one():
    with SessionLocal() as s:
        target = _subject(s, major="  ")
        source = _subject(s, major="金融", gpa_score=Decimal("88"), gpa_scale=Decimal("100"), english_score="IELTS 7")
        merge_subject(s, source, target)
        took = s.get(Profile, target)
        assert (took.major, took.gpa_score, took.english_score) == ("金融", Decimal("88"), "IELTS 7")
        s.rollback()


def test_portfolio_rows_merge_and_the_account_keeps_its_band_and_first_choice():
    with SessionLocal() as s:
        target = _subject(s)
        source = _subject(s)
        _app(s, target, P, "冲", primary=True)
        _app(s, source, P, "保", primary=False)
        _app(s, source, Q, "稳", primary=True)
        merge_subject(s, source, target)
        rows = {r.program_id: r for r in s.scalars(select(Application).where(Application.client_id == target))}
        assert {k: r.tier for k, r in rows.items()} == {P: "冲", Q: "稳"}
        assert [k for k, r in rows.items() if r.is_primary] == [P]
        s.rollback()


def test_the_anonymous_first_choice_survives_when_the_account_has_none():
    with SessionLocal() as s:
        target = _subject(s)
        source = _subject(s)
        _app(s, target, P, "冲")
        _app(s, source, Q, "稳", primary=True)
        merge_subject(s, source, target)
        primary = s.scalars(select(Application.program_id).where(Application.client_id == target, Application.is_primary)).all()
        assert primary == [Q]
        s.rollback()


def test_tasks_merge_and_materials_follow_to_the_accounts_task():
    with SessionLocal() as s:
        target = _subject(s)
        source = _subject(s)
        kept = _task(s, target, MATERIAL)
        duplicate = _task(s, source, MATERIAL)
        moved = _task(s, source, OTHER)
        doc_on_duplicate = _doc(s, source, duplicate.id)
        doc_on_moved = _doc(s, source, moved.id)
        loose = _doc(s, source)
        s.add(TaskEvent(id=str(uuid.uuid4()), client_id=source, task_id=moved.id, actor="user", event="updated"))
        s.flush()
        merge_subject(s, source, target)
        tasks = {t.material_key: t.id for t in s.scalars(select(RoadmapTask).where(RoadmapTask.client_id == target))}
        assert tasks == {MATERIAL: kept.id, OTHER: moved.id}
        docs = {d.id: d for d in s.scalars(select(Document).where(Document.client_id == target))}
        assert set(docs) == {doc_on_duplicate.id, doc_on_moved.id, loose.id}
        assert docs[doc_on_duplicate.id].task_id == kept.id
        assert docs[doc_on_moved.id].task_id == moved.id
        assert s.scalars(select(TaskEvent.client_id).where(TaskEvent.task_id == moved.id)).all() == [target]
        s.rollback()


# ---------- through the login route ----------


def _anonymous_browser_with_data(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    browser = new_client()
    assert browser.patch("/api/profile", json={"major": "匿名专业", "targetField": "计算机"}).status_code == 200
    rows = [{"programId": P, "tier": "稳", "isPrimary": True}, {"programId": Q, "tier": "保"}]
    assert browser.put("/api/applications", json={"rows": rows}).status_code == 200
    assert browser.post("/api/documents", files=an_upload()).status_code == 201
    anonymous = browser.cookies.get(COOKIE_NAME)
    monkeypatch.setattr(settings, "auth_enabled", True)
    return browser, anonymous


def test_first_login_claims_the_browsers_anonymous_data(login_mode, monkeypatch):
    browser, anonymous = _anonymous_browser_with_data(monkeypatch)
    body = login(browser, login_mode)
    assert body["created"] is True
    with SessionLocal() as s:
        account = s.scalar(select(Account).where(Account.email == body["account"]["email"]))
        assert account.client_id == anonymous
    assert browser.get("/api/profile").json()["major"] == "匿名专业"
    assert {r["programId"] for r in browser.get("/api/applications").json()} == {P, Q}
    assert len(browser.get("/api/documents").json()) == 1
    assert browser.cookies.get(COOKIE_NAME) is None


def test_login_to_an_existing_account_merges_without_overwriting(login_mode, monkeypatch):
    email = unique_email()
    elsewhere = new_client()
    login(elsewhere, login_mode, email)
    elsewhere.patch("/api/profile", json={"major": "账号专业"})
    elsewhere.put("/api/applications", json={"rows": [{"programId": P, "tier": "冲", "isPrimary": True}]})

    browser, anonymous = _anonymous_browser_with_data(monkeypatch)
    _age_codes(email, 61)
    body = login(browser, login_mode, email)
    assert body["created"] is False
    assert body["merged"]["applications"] == 1 and body["merged"]["documents"] == 1
    assert browser.get("/api/profile").json()["major"] == "账号专业"
    rows = {r["programId"]: r for r in browser.get("/api/applications").json()}
    assert {k: r["tier"] for k, r in rows.items()} == {P: "冲", Q: "保"}
    assert [k for k, r in rows.items() if r["isPrimary"]] == [P]
    assert len(browser.get("/api/documents").json()) == 1
    with SessionLocal() as s:
        assert s.get(Client, anonymous) is None


def test_a_claimed_cookie_is_not_merged_into_a_second_account(login_mode, monkeypatch):
    browser, anonymous = _anonymous_browser_with_data(monkeypatch)
    login(browser, login_mode)
    # A stale copy of the same anonymous cookie, presented by another login.
    other = new_client()
    other.cookies.set(COOKIE_NAME, anonymous)
    body = login(other, login_mode)
    assert body["created"] is True and body["merged"] == {}
    assert other.get("/api/applications").json() == []
    assert len(browser.get("/api/applications").json()) == 2
