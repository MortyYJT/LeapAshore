"""The knowledge-gap review queue (openspec/changes/knowledge-gaps, TASKS.md P2 #1).

Refusals are recorded as reports of a gap (the asker only as a keyed hash), deleted with the subject and
after 90 days; an admin lists, reads and reviews gaps; a review queues a re-collection on the collection
queue. Tasks are never sent to a broker here: the sender is replaced and what it was given is checked.
"""

import json
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import cleanup, roles
from app import knowledge_gaps as gaps_cli
from app.agent import graph as graph_module
from app.agent import intent
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models.account import Account
from app.models.collect import CollectPage, PageState
from app.models.knowledge_gap import KnowledgeGap, KnowledgeGapReport
from app.models.program import University
from app.services import knowledge_gaps as kg
from app.services.accounts import delete_subject, merge_subject
from tests.auth_helpers import login, login_mode, new_client, outbox, unique_email  # noqa: F401 - fixtures
from tests.model_outage import out_of_balance_model
from tests.test_snapshot_rag import Answering, school  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("require_db")

ADMIN = "/api/admin/knowledge-gaps"
KEY = "test-gap-hash-key"


@pytest.fixture
def recording(monkeypatch):
    """Recording on (the suite turns it off), a hash key, and every gap a test makes removed after it."""
    monkeypatch.setattr(settings, "knowledge_gaps_record", True)
    monkeypatch.setattr(settings, "knowledge_gap_hash_key", KEY)
    with SessionLocal() as s:
        before = set(s.scalars(select(KnowledgeGap.id)))
    yield
    with SessionLocal() as s:
        made = set(s.scalars(select(KnowledgeGap.id))) - before
        if made:
            s.execute(delete(KnowledgeGap).where(KnowledgeGap.id.in_(made)))
            s.commit()


def uid(prefix="test-gap-") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def record(subject: str, *, schools=("u1",), reason="school_not_collected", question="墨大数据科学雅思？", **kw) -> str:
    with SessionLocal() as s:
        return kg.record(s, route=kw.pop("route", "requirements"), reason=reason, question=question, subject=subject,
                         schools=list(schools), fields=kw.pop("fields", ["计算机与数据"]),
                         subject_words=kw.pop("subject_words", ["数据科学"]), topics=kw.pop("topics", []), **kw)


def gap(gap_id: str) -> KnowledgeGap:
    with SessionLocal() as s:
        row = s.get(KnowledgeGap, gap_id)
        s.expunge(row)
        return row


def reports(gap_id: str) -> list[KnowledgeGapReport]:
    with SessionLocal() as s:
        rows = list(s.scalars(select(KnowledgeGapReport).where(KnowledgeGapReport.gap_id == gap_id)))
        for r in rows:
            s.expunge(r)
        return rows


# ---- the key and the hash (no database) ----------------------------------------------------------------


def test_the_key_ignores_order_and_folds_words():
    a = kg.gap_key("requirements", "school_not_collected", ["u2", "u1"], ["商科", "计算机"], ["Data Science"], [], "x")
    b = kg.gap_key("requirements", "school_not_collected", ["u1", "u2"], ["计算机", "商科"], ["data  science"], [], "y")
    assert a == b
    assert a != kg.gap_key("requirements", "no_program_in_field", ["u1", "u2"], ["计算机", "商科"], ["data science"], [], "x")
    assert a != kg.gap_key("passages", "school_not_collected", ["u1", "u2"], ["计算机", "商科"], ["data science"], [], "x")


def test_without_a_school_the_question_tells_gaps_apart():
    same = kg.gap_key("requirements", "no_school", [], [], [], [], "早稻田大学 的 雅思要求？")
    assert same == kg.gap_key("requirements", "no_school", [], [], [], [], "早稻田大学的雅思要求")
    assert same != kg.gap_key("requirements", "no_school", [], [], [], [], "庆应大学的雅思要求")


def test_the_reporter_is_a_keyed_hash_of_the_subject(monkeypatch):
    subject = str(uuid.uuid4())
    monkeypatch.setattr(settings, "knowledge_gap_hash_key", KEY)
    first = kg.reporter_hash(subject)
    assert first == kg.reporter_hash(subject) and len(first) == 64 and subject not in first
    monkeypatch.setattr(settings, "knowledge_gap_hash_key", "another key")
    assert kg.reporter_hash(subject) != first
    monkeypatch.setattr(settings, "knowledge_gap_hash_key", "")
    assert kg.reporter_hash(subject) is None


# ---- recording -------------------------------------------------------------------------------------------


def test_refusals_with_one_key_add_to_one_gap_and_store_no_identity(recording):
    school_id, a, b = uid(), str(uuid.uuid4()), str(uuid.uuid4())
    first = record(a, schools=[school_id])
    second = record(b, schools=[school_id], question="墨尔本大学 data science 语言要求")
    record(a, schools=[school_id])
    assert first == second
    row = gap(first)
    assert row.report_count == 3 and row.status == kg.OPEN and row.university_ids == [school_id]
    stored = reports(first)
    assert {r.reporter_hash for r in stored} == {kg.reporter_hash(a), kg.reporter_hash(b)}
    for r in stored:
        assert a not in json.dumps([r.reporter_hash, r.question]) and b not in json.dumps([r.reporter_hash, r.question])
    with SessionLocal() as s:
        shown = kg.show_gap(s, first)
    assert shown["reports"] == 3 and shown["askers"] == 2
    assert shown["questions"][0]["question"] == "墨大数据科学雅思？"  # newest first


def test_concurrent_refusals_are_all_counted(recording):
    school_id = uid()
    ids: list[str] = []
    errors: list[BaseException] = []

    def one():
        try:
            ids.append(record(str(uuid.uuid4()), schools=[school_id]))
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(set(ids)) == 1
    assert gap(ids[0]).report_count == 8 and len(reports(ids[0])) == 8


def test_a_long_question_is_cut(recording):
    gap_id = record(str(uuid.uuid4()), schools=[uid()], question="问" * 900)
    assert len(reports(gap_id)[0].question) == kg.QUESTION_CHARS


def test_without_a_key_the_question_is_not_kept_but_the_gap_counts(recording, monkeypatch):
    """Without a key a report could not be found again to delete with its subject (review of #67)."""
    monkeypatch.setattr(settings, "knowledge_gap_hash_key", "")
    gap_id = record(str(uuid.uuid4()), schools=[uid()])
    assert reports(gap_id) == [] and gap(gap_id).report_count == 1
    with SessionLocal() as s:
        shown = kg.show_gap(s, gap_id)
    assert (shown["reports"], shown["keptReports"], shown["questions"]) == (1, 0, [])


def test_nothing_is_recorded_while_recording_is_off(recording, monkeypatch):
    monkeypatch.setattr(settings, "knowledge_gaps_record", False)
    school_id = uid()
    kg.record_safely(route="requirements", reason="school_not_collected", question="q", subject="s",
                     schools=[school_id])
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(KnowledgeGap)
                        .where(KnowledgeGap.university_ids.contains([school_id]))) == 0


def test_a_failure_to_record_is_swallowed(recording, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(kg, "record", broken)
    assert kg.record_safely(route="requirements", reason="no_school", question="q", subject="s") is None


# ---- deletion, merge, retention --------------------------------------------------------------------------


def test_deleting_a_subject_deletes_its_reports_and_keeps_the_gap(recording):
    school_id, leaving, staying = uid(), str(uuid.uuid4()), str(uuid.uuid4())
    gap_id = record(leaving, schools=[school_id])
    record(staying, schools=[school_id])
    with SessionLocal() as s:
        delete_subject(s, leaving)
    assert [r.reporter_hash for r in reports(gap_id)] == [kg.reporter_hash(staying)]
    assert gap(gap_id).report_count == 2


def test_a_merge_moves_the_reports_to_the_account(recording):
    from app.deps import load_or_create_profile

    source, target = str(uuid.uuid4()), str(uuid.uuid4())
    with SessionLocal() as s:
        load_or_create_profile(s, source)
        load_or_create_profile(s, target)
        s.commit()
    gap_id = record(source, schools=[uid()])
    with SessionLocal() as s:
        merge_subject(s, source, target)
        s.commit()
    assert [r.reporter_hash for r in reports(gap_id)] == [kg.reporter_hash(target)]
    with SessionLocal() as s:
        delete_subject(s, target)
    assert reports(gap_id) == []


def test_reports_older_than_the_retention_are_swept_and_the_gap_stays(recording):
    school_id = uid()
    old = record(str(uuid.uuid4()), schools=[school_id])
    record(str(uuid.uuid4()), schools=[school_id])
    with SessionLocal() as s:
        oldest = s.scalars(select(KnowledgeGapReport).where(KnowledgeGapReport.gap_id == old)
                           .order_by(KnowledgeGapReport.created_at)).first()
        oldest.created_at = datetime.now(UTC) - timedelta(days=settings.knowledge_gap_retention_days + 1)
        s.commit()
        assert kg.sweep_reports(s, apply=False)["old_gap_reports"] >= 1
        assert len(reports(old)) == 2
        kg.sweep_reports(s, apply=True)
    assert len(reports(old)) == 1 and gap(old).report_count == 2


def test_the_daily_cleanup_sweeps_reports_in_both_modes(monkeypatch):
    from app import worker

    called = []
    monkeypatch.setattr(kg, "sweep_reports", lambda session, apply, now=None: called.append(apply) or {"old_gap_reports": 0})
    monkeypatch.setattr(settings, "auth_enabled", False)
    worker.cleanup.apply()
    with SessionLocal() as s:
        cleanup.run(s, apply=False)
    assert called == [True, False]


# ---- recording from the advisor ---------------------------------------------------------------------------


def ask(question: str, intent_name: str = "官方要求核验", client: TestClient | None = None) -> list[dict]:
    client = client or TestClient(app)
    response = client.post("/api/advisor/chat", json={"conversationId": f"g{uuid.uuid4().hex[:8]}", "message": question})
    assert response.status_code == 200
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def advisor(monkeypatch, recording):
    async def requirement(query, history):
        return {"intent": "官方要求核验", "confidence": 0.9}

    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(intent, "classify", requirement)
    monkeypatch.setattr(settings, "advisor_subject_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1000/60")


def gaps_for(university_id: str) -> list[KnowledgeGap]:
    with SessionLocal() as s:
        rows = list(s.scalars(select(KnowledgeGap).where(KnowledgeGap.university_ids.contains([university_id]))))
        for r in rows:
            s.expunge(r)
        return rows


def test_a_gate_refusal_in_a_turn_is_recorded(school, advisor):  # noqa: F811
    events = ask("无页面测试大学的学费多少？")
    assert "已记录为待采集" in "".join(e.get("text", "") for e in events if e["type"] == "token")
    [row] = gaps_for(school["empty"])
    assert (row.route, row.reason, row.topics) == ("passages", "school_not_collected", ["tuition"])
    # The node was given the turn's config: the asker is the turn's subject.
    assert [r.reporter_hash is not None for r in reports(row.id)] == [True]
    ask("无页面测试大学学费是多少")
    assert gaps_for(school["empty"])[0].report_count == 2


def test_an_answer_with_nothing_checkable_is_recorded(school, advisor, monkeypatch):  # noqa: F811
    args = {"sentences": [{"text": "学费大约 6 万美元。", "citations": []}]}
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kw: Answering(arguments=args))
    ask("切片检索测试大学数据科学硕士学费多少？")
    [row] = gaps_for(school["uid"])
    assert (row.route, row.reason) == ("passages", "nothing_checkable")


def test_an_answer_the_judge_could_not_check_is_not_a_gap(school, advisor, monkeypatch):  # noqa: F811
    args = {"sentences": [{"text": "数据科学硕士学费每年 61,000 美元。",
                           "citations": [{"passage": 1, "quote": "Tuition fee: US$61,000 per year."}]}]}
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kw: Answering(arguments=args, verdicts=[]))
    events = ask("切片检索测试大学数据科学硕士学费多少？")
    assert "不作判断" in "".join(e.get("text", "") for e in events if e["type"] == "token")
    assert gaps_for(school["uid"]) == []


def test_a_model_outage_is_not_a_gap(school, advisor, monkeypatch):  # noqa: F811
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kw: out_of_balance_model())
    events = ask("切片检索测试大学数据科学硕士学费多少？")
    assert [e["code"] for e in events if e["type"] == "error"] == ["model_unavailable"]
    assert gaps_for(school["uid"]) == []


def test_a_turn_whose_recording_fails_still_refuses(school, advisor, monkeypatch):  # noqa: F811
    def broken(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(kg, "record", broken)
    events = ask("无页面测试大学的学费多少？")
    assert "已记录为待采集" in "".join(e.get("text", "") for e in events if e["type"] == "token")
    assert [e for e in events if e["type"] == "error"] == []


def test_a_school_left_out_of_a_requirement_answer_is_recorded(recording, monkeypatch):
    missing = uid()

    def strong(session, query, ranking=None):
        return {"evidence_strong": True, "evidence": "[1] x", "citations": [],
                "trace": {"evidence_gate": "strong", "gate_signals": {
                    "schools": ["kept", missing], "missing_schools": [missing], "fields": ["商科与金融"],
                    "subject_words": ["金融"]}}}

    monkeypatch.setattr(graph_module.evidence, "gate", strong)
    graph_module.retrieve_requirements({"messages": [graph_module.HumanMessage(content="两校金融硕士要求")]},
                                       {"configurable": {"client_id": str(uuid.uuid4())}})
    [row] = gaps_for(missing)
    assert (row.reason, row.university_ids, row.subject_words) == ("school_missing", [missing], ["金融"])


# ---- review: who may ------------------------------------------------------------------------------------


def test_the_review_api_is_refused_in_anonymous_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    response = TestClient(app).get(ADMIN)
    assert response.status_code == 403


def test_the_review_api_needs_a_session_and_the_admin_role(login_mode):  # noqa: F811
    client = new_client()
    assert client.get(ADMIN).status_code == 401
    email = unique_email()
    login(client, login_mode, email)
    assert client.get(ADMIN).status_code == 403
    with SessionLocal() as s:
        roles.grant(s, email)
    assert client.get(ADMIN).status_code == 200
    with SessionLocal() as s:
        roles.revoke(s, email)
    assert client.get(ADMIN).status_code == 403


def test_the_role_command_grants_lists_and_refuses_an_unknown_email(login_mode, capsys):  # noqa: F811
    email = unique_email()
    login(new_client(), login_mode, email)
    assert roles.main(["grant", email]) == 0
    assert roles.main(["list"]) == 0 and email in capsys.readouterr().out
    assert roles.main(["revoke", email]) == 0
    assert roles.main(["grant", unique_email()]) == 1


@pytest.fixture
def admin(login_mode, recording):  # noqa: F811
    client = new_client()
    email = unique_email()
    login(client, login_mode, email)
    with SessionLocal() as s:
        roles.grant(s, email)
        account_id = s.scalar(select(Account.id).where(Account.email == email))
    client.account_id = account_id
    return client


# ---- review: what it does ------------------------------------------------------------------------------


@pytest.fixture
def collected(monkeypatch):
    """A university whose id is a collection key, with pages in every state, and a fake `_schools.json`."""
    key = uid("test-gapschool-")
    other = uid("test-gapschool-")
    with SessionLocal() as s:
        s.add(University(id=key, name="缺口测试大学", name_en="Gap Test University", country="美国"))
        pages = {}
        for state in (PageState.FAILED, PageState.DEFERRED, PageState.PENDING, PageState.BLOCKED, PageState.DONE,
                      PageState.NEEDS_HUMAN):
            page = CollectPage(id=str(uuid.uuid4()), school_key=key, url=f"https://gap.example/{state}", program_name="MSc",
                               state=state, attempts=0)
            s.add(page)
            pages[state] = page.id
        s.commit()
    schools = {key: {"school_key": key, "name_en": "Gap Test University", "listing_urls": ["https://gap.example/list"]},
               other: {"school_key": other, "name_en": "Unlisted Test University", "listing_urls": []}}
    monkeypatch.setattr(kg, "load_schools", lambda: schools)
    sent: list[tuple] = []
    monkeypatch.setattr(kg, "send_tasks", lambda pages, discover, budget_key, cap: sent.append((sorted(pages), discover, budget_key, cap)))
    yield {"key": key, "other": other, "pages": pages, "sent": sent}
    with SessionLocal() as s:
        s.execute(delete(CollectPage).where(CollectPage.school_key.in_([key, other])))
        s.execute(delete(University).where(University.id == key))
        s.commit()


def page_state(page_id: str) -> str:
    with SessionLocal() as s:
        return s.get(CollectPage, page_id).state


def test_an_admin_lists_and_reads_gaps(admin, collected):
    gap_id = record(str(uuid.uuid4()), schools=[collected["key"]])
    listed = admin.get(ADMIN).json()
    mine = next(g for g in listed["gaps"] if g["id"] == gap_id)
    assert mine["reports"] == 1 and mine["askers"] == 1 and mine["schools"] == [
        {"id": collected["key"], "name": "缺口测试大学"}]
    one = admin.get(f"{ADMIN}/{gap_id}").json()
    assert one["questions"][0]["question"] == "墨大数据科学雅思？"
    assert "reporter_hash" not in json.dumps(one)
    assert admin.get(f"{ADMIN}/{uuid.uuid4()}").status_code == 404


def test_a_recollect_review_queues_the_school_and_never_a_blocked_page(admin, collected):
    gap_id = record(str(uuid.uuid4()), schools=[collected["key"]])
    response = admin.post(f"{ADMIN}/{gap_id}/review", json={"decision": "recollect", "note": "补采"})
    assert response.status_code == 200, response.text
    pages = collected["pages"]
    requeued = sorted(pages[s] for s in (PageState.FAILED, PageState.DEFERRED, PageState.PENDING))
    [(sent_pages, discover, budget_key, cap)] = collected["sent"]
    assert sent_pages == requeued and discover == [collected["key"]]
    assert budget_key.startswith("daily:") and cap == settings.collect_daily_budget_cny
    for state in (PageState.FAILED, PageState.DEFERRED, PageState.PENDING):
        assert page_state(pages[state]) == PageState.QUEUED
    for state in (PageState.BLOCKED, PageState.DONE, PageState.NEEDS_HUMAN):
        assert page_state(pages[state]) == state
    row = gap(gap_id)
    assert row.status == kg.RECOLLECT_QUEUED and row.reviewed_by == admin.account_id and row.review_note == "补采"
    assert row.recollect["schools"] == [{"schoolKey": collected["key"], "requeued": 3, "discovery": True}]
    # A later refusal of the same gap is counted as arriving after the review.
    record(str(uuid.uuid4()), schools=[collected["key"]])
    assert admin.get(f"{ADMIN}/{gap_id}").json()["reportsSinceReview"] == 1


def test_a_gap_with_nothing_to_send_is_refused_and_stays_open(admin, collected):
    gap_id = record(str(uuid.uuid4()), schools=[uid("test-unknown-")])
    response = admin.post(f"{ADMIN}/{gap_id}/review", json={"decision": "recollect"})
    assert response.status_code == 409
    assert gap(gap_id).status == kg.OPEN and collected["sent"] == []
    # A school with no pages and no listing URL has nothing to send either.
    response = admin.post(f"{ADMIN}/{gap_id}/review", json={"decision": "recollect", "schoolKeys": [collected["other"]]})
    assert response.status_code == 409


def test_a_no_school_gap_is_sent_to_the_school_the_reviewer_names(admin, collected):
    gap_id = record(str(uuid.uuid4()), schools=[], reason="no_school", fields=[], subject_words=[], question="缺口大学雅思？")
    response = admin.post(f"{ADMIN}/{gap_id}/review", json={"decision": "recollect", "schoolKeys": [collected["key"]]})
    assert response.status_code == 200
    assert collected["sent"][0][1] == [collected["key"]]
    assert admin.post(f"{ADMIN}/{gap_id}/review", json={"decision": "recollect", "schoolKeys": ["../etc"]}).status_code == 422


def test_a_dismissed_gap_keeps_counting(admin, collected):
    gap_id = record(str(uuid.uuid4()), schools=[collected["key"]])
    assert admin.post(f"{ADMIN}/{gap_id}/review", json={"decision": "dismiss", "note": "不在范围"}).status_code == 200
    assert gap(gap_id).status == kg.DISMISSED and collected["sent"] == []
    assert gap_id not in [g["id"] for g in admin.get(ADMIN).json()["gaps"]]
    assert gap_id in [g["id"] for g in admin.get(ADMIN, params={"status": "dismissed"}).json()["gaps"]]


def test_a_failed_send_leaves_the_gap_and_the_pages_as_they_were(admin, collected, monkeypatch):
    def down(*args, **kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(kg, "send_tasks", down)
    gap_id = record(str(uuid.uuid4()), schools=[collected["key"]])
    response = admin.post(f"{ADMIN}/{gap_id}/review", json={"decision": "recollect", "note": "补采"})
    assert response.status_code == 503
    row = gap(gap_id)
    assert row.status == kg.OPEN and row.reviewed_at is None and row.reviewed_by is None and row.recollect is None
    assert "broker down" in row.review_note
    pages = collected["pages"]
    for state in (PageState.FAILED, PageState.DEFERRED, PageState.PENDING):
        assert page_state(pages[state]) == state
    # With the broker back, the same review queues the same pages.
    monkeypatch.setattr(kg, "send_tasks", lambda p, d, b, c: collected["sent"].append((sorted(p), d, b, c)))
    assert admin.post(f"{ADMIN}/{gap_id}/review", json={"decision": "recollect"}).status_code == 200
    assert collected["sent"][0][0] == sorted(pages[s] for s in (PageState.FAILED, PageState.DEFERRED, PageState.PENDING))


def test_the_command_line_lists_and_reviews(recording, collected, capsys):
    gap_id = record(str(uuid.uuid4()), schools=[collected["key"]])
    assert gaps_cli.main(["list"]) == 0
    assert gap_id in capsys.readouterr().out
    assert gaps_cli.main(["show", gap_id]) == 0
    assert "墨大数据科学雅思" in capsys.readouterr().out
    assert gaps_cli.main(["review", gap_id, "recollect"]) == 0
    assert gap(gap_id).status == kg.RECOLLECT_QUEUED and gap(gap_id).reviewed_by is None
