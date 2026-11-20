"""The advisor's application tools through the real endpoints: the stream, the checkpointer, the confirm.

`test_application_tools.py` calls the tools with the confirm step stubbed. Here the real graph runs on a
scripted model, pauses on `interrupt`, and is answered through `POST /api/advisor/confirm`, so these
tests cover what only the whole path can show: what the confirm card carries, that the applicant's
messages reach the tool, and that a confirmed change is written exactly once under a second click, a
restart, a process killed after the write, and two confirms at the same moment.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from sqlalchemy import func, select

from app.agent import checkpoint, graph as graph_module, halt, intent, steps
from app.agent.graph import CONFIRMED_TOOLS, build_graph, one_change_per_step
from app.config import settings
from app.db import SessionLocal
from app.deps import COOKIE_NAME
from app.main import app
from app.models.application_plan import ApplicationPlan
from app.routers import advisor
from app.services import application_records as records
from app.services.accounts import delete_subject
from app.services.application_records import RecordPatch
from tests.test_advisor_steps import ask, call, events, last, life, opened, step_events
from tests.test_application_tools import SOURCE, all_records, catalogue, future, new_applicant, record  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_db")

API_DIR = Path(__file__).resolve().parent.parent
CHAT, CONFIRM = "/api/advisor/chat", "/api/advisor/confirm"
USAGE = {"input_tokens": 40, "output_tokens": 2, "total_tokens": 42}
NOTHING_PENDING = "没有待确认的操作，可能已经处理过或已过期。"
ROUNDS = 10


class Proposes(BaseChatModel):
    """Asks for one tool call on the applicant's message, and repeats the tool's answer after it.
    `by_conversation` gives a different call per conversation, keyed by a word in the message."""

    tool: str = ""
    arguments: dict = {}
    by_message: dict = {}
    delay: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "proposes"

    def bind_tools(self, tools, **kwargs):
        return self

    def _reply(self, messages) -> AIMessage:
        last_message = messages[-1]
        if isinstance(last_message, ToolMessage):
            return AIMessage(content=f"好的。{last_message.content}", usage_metadata=USAGE)
        name, arguments = self.tool, self.arguments
        for word, (other_name, other_arguments) in self.by_message.items():
            if word in str(last_message.content):
                name, arguments = other_name, other_arguments
        made = {"name": name, "args": arguments, "id": f"call-{uuid.uuid4().hex[:8]}"}
        return AIMessage(content="", tool_calls=[made], usage_metadata=USAGE)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(self.delay)
        return self._generate(messages)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(self.delay)
        reply = self._reply(messages)
        calls = [{"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": 0} for c in reply.tool_calls]
        chunk = AIMessageChunk(content=reply.content, tool_call_chunks=calls, usage_metadata=USAGE)
        if run_manager and reply.content:
            await run_manager.on_llm_new_token(reply.content, chunk=ChatGenerationChunk(message=chunk))
        yield ChatGenerationChunk(message=chunk)


class Service:
    """The API's graph on a checkpointer of its own, so a test can "restart" the service."""

    def __init__(self, monkeypatch) -> None:
        self.monkeypatch = monkeypatch
        self.savers: list[checkpoint.Checkpointer] = []
        self.start()

    def start(self) -> None:
        saver = checkpoint.Checkpointer()
        self.savers.append(saver)
        self.monkeypatch.setattr(advisor, "graph", build_graph(checkpointer=saver))

    def restart(self) -> None:
        self.savers[-1].close()
        self.start()

    def close(self) -> None:
        for saver in self.savers:
            saver.close()


@pytest.fixture
def service(monkeypatch):
    running = Service(monkeypatch)
    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(settings, "advisor_subject_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1000/60")

    async def operation(query, history):
        return {"intent": "业务操作", "confidence": 1.0}

    monkeypatch.setattr(intent, "classify", operation)
    yield running
    running.close()
    advisor._running.clear()
    halt._requested.clear()


@pytest.fixture
def propose(monkeypatch, service):
    """Make the model ask for one call: `propose("propose_application_status", application_id=..., status=...)`."""

    def use(tool: str = "", by_message: dict | None = None, **arguments) -> Proposes:
        model = Proposes(tool=tool, arguments=arguments, by_message=by_message or {})
        monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: model)
        return model

    return use


@pytest.fixture
def applicant(catalogue):  # noqa: F811
    """A signed-in browser whose subject has one catalogue application and one manual one."""
    client_id = new_applicant([catalogue["first"]])
    with SessionLocal() as s:
        manual, _ = records.create_record(
            s, client_id, records.RecordCreate(school="Example University", name="Example MSc"), f"k-{uuid.uuid4().hex}"
        )
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, client_id)
    return {"id": client_id, "client": client, "catalog": f"catalog:{catalogue['first']}", "manual": manual["id"],
            **catalogue}


def confirm_of(evts: list[dict]) -> dict:
    cards = [e for e in evts if e["type"] == "confirm"]
    assert len(cards) == 1, evts
    return cards[0]


def answer(client: TestClient, card: dict, approved: bool = True, conversation: str = "c1") -> list[dict]:
    response = client.post(CONFIRM, json={"conversationId": conversation, "approved": approved, "interruptId": card["id"]})
    assert response.status_code == 200
    return events(response)


def said(evts: list[dict]) -> str:
    return "".join(e.get("text", "") for e in evts if e["type"] == "token")


def errors(evts: list[dict]) -> list[str]:
    return [e["message"] for e in evts if e["type"] == "error"]


def version_of(plan_id: str) -> int:
    with SessionLocal() as s:
        return s.scalar(select(ApplicationPlan.version).where(ApplicationPlan.id == plan_id))


def manual_rows(client_id: str) -> int:
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(ApplicationPlan).where(
            ApplicationPlan.client_id == client_id, ApplicationPlan.catalog_program_id.is_(None)))


# ---------------------------------------------------------------------------------------------------
# The card and the write, for each kind of change
# ---------------------------------------------------------------------------------------------------


def kinds(applicant: dict) -> dict:
    """One proposal of each kind: the message, the call, the card's lines and how to tell it was written."""
    when = future(77).isoformat()
    return {
        "status": {
            "message": "把我手动加的那个申请标成已提交",
            "call": ("propose_application_status", {"application_id": applicant["manual"], "status": "submitted"}),
            "title": "提议改状态",
            "args": [{"label": "申请", "value": "Example University Example MSc"}, {"label": "状态", "value": "已提交"}],
            "changes": [{"label": "申请状态", "before": "考虑中", "after": "已提交"}],
            "key": applicant["manual"], "written": lambda r: r["status"] == "submitted",
        },
        "stated deadline": {
            "message": f"手动加的那个申请，截止日期是 {when}",
            "call": ("propose_application_deadline", {"application_id": applicant["manual"], "stated_deadline": when}),
            "title": "提议改日期",
            "args": [{"label": "申请", "value": "Example University Example MSc"}, {"label": "日期", "value": when}],
            "changes": [{"label": "截止日期", "before": None, "after": when},
                        {"label": "日期来源", "before": None, "after": "你在对话里说的，待核对"}],
            "key": applicant["manual"], "written": lambda r: r["deadline"].isoformat() == when and r["checkedAt"] is None,
        },
        "catalogue deadline": {
            "message": "学校库那个项目我报第二轮",
            "call": ("propose_application_deadline", {"application_id": applicant["catalog"], "catalog_deadline_id": applicant["round2"]}),
            "title": "提议改日期",
            "args": None,
            "changes": [{"label": "轮次", "before": None, "after": "Round 2"},
                        {"label": "截止日期", "before": applicant["round1_date"].isoformat(), "after": applicant["round2_date"].isoformat()},
                        {"label": "日期来源", "before": None, "after": "学校库采集（example.edu），待核对"}],
            "key": applicant["catalog"],
            "written": lambda r: (r["round"], r["deadline"], r["sourceUrl"], r["deadlineOrigin"], r["checkedAt"])
            == ("Round 2", applicant["round2_date"], SOURCE, "collected", None),
        },
        "material": {
            "message": "手动加的那个申请材料都齐了，另外记一下：成绩单已寄出",
            "call": ("propose_material_tick", {"application_id": applicant["manual"], "ready": True, "add_note": "成绩单已寄出"}),
            "title": "提议改材料",
            "args": [{"label": "申请", "value": "Example University Example MSc"}, {"label": "材料", "value": "勾上（全部就绪）"},
                     {"label": "备注", "value": "成绩单已寄出"}],
            "changes": [{"label": "材料", "before": "准备中", "after": "已就绪（自查）"},
                        {"label": "材料备注", "before": None, "after": "加一行：成绩单已寄出"}],
            "key": applicant["manual"], "written": lambda r: r["materialsReady"] and r["materialNotes"] == "成绩单已寄出",
        },
        "manual application": {
            "message": "帮我手动加一个申请：Another University 的 MSc Robotics",
            "call": ("propose_manual_application", {"school": "Another University", "name": "MSc Robotics"}),
            "title": "提议加申请",
            "args": [{"label": "学校", "value": "Another University"}, {"label": "项目", "value": "MSc Robotics"}],
            "changes": [{"label": "我的申请", "before": None, "after": "加入（手动添加）"},
                        {"label": "申请状态", "before": None, "after": "考虑中"},
                        {"label": "截止日期", "before": None, "after": "待确认"}],
            "key": None, "written": None,
        },
    }


KINDS = ["status", "stated deadline", "catalogue deadline", "material", "manual application"]


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_of_change_waits_on_a_card_and_is_written_only_after_the_yes(propose, applicant, kind):
    case = kinds(applicant)[kind]
    tool, arguments = case["call"]
    propose(tool, **arguments)
    before = all_records(applicant["id"])

    evts = ask(applicant["client"], case["message"])

    start = opened(evts, tool)
    assert start["title"] == case["title"]
    if case["args"] is not None:
        assert start["args"] == case["args"]
    assert "write" not in start
    assert life(evts, start["id"]) == ["running", "waiting"]
    card = confirm_of(evts)
    assert card["tool"] == tool and card["kind"] == "confirm_application" and card["stepId"] == start["id"]
    assert card["changes"] == case["changes"]
    assert card["target"]["school"] and card["target"]["program"]
    # The version the card was drawn from stays on the server.
    assert "base" not in card
    assert all_records(applicant["id"]) == before, "nothing is written while the card waits"

    replied = answer(applicant["client"], card)

    assert errors(replied) == []
    assert last(replied, start["id"])["result"] == steps.CONFIRMED
    write = last(replied, f"{start['id']}:write")
    assert (write["status"], write["result"], write["write"]) == ("done", "已保存", True)
    assert said(replied).startswith("好的。已执行：")
    if case["key"]:
        assert case["written"](record(applicant["id"], case["key"]))
    else:
        added = [r for r in all_records(applicant["id"]) if r["school"] == "Another University"]
        assert len(added) == 1 and added[0]["deadline"] is None and added[0]["id"] in said(replied)
    # The same click again finds nothing to do.
    assert errors(answer(applicant["client"], card)) == [NOTHING_PENDING]


@pytest.mark.parametrize("kind", KINDS)
def test_a_declined_card_writes_nothing(propose, applicant, kind):
    case = kinds(applicant)[kind]
    tool, arguments = case["call"]
    propose(tool, **arguments)
    before = all_records(applicant["id"])
    evts = ask(applicant["client"], case["message"])
    start = opened(evts, tool)

    replied = answer(applicant["client"], confirm_of(evts), approved=False)

    closed = last(replied, start["id"])
    assert (closed["status"], closed["result"]) == ("declined", steps.DECLINED_NOTE)
    assert not [e for e in step_events(replied) if e["id"].endswith(":write")]
    assert "用户取消了操作" in said(replied)
    assert all_records(applicant["id"]) == before


# ---------------------------------------------------------------------------------------------------
# A made-up date does not reach a card
# ---------------------------------------------------------------------------------------------------


def test_a_date_the_applicant_did_not_write_never_becomes_a_card(propose, applicant):
    made_up = future(140).isoformat()
    propose("propose_application_deadline", application_id=applicant["manual"], stated_deadline=made_up)

    evts = ask(applicant["client"], "帮我把手动加的那个申请的截止日期填上，你知道的那个就行")

    closed = last(evts, opened(evts, "propose_application_deadline")["id"])
    assert closed["status"] == "failed" and "没有写出" in closed["result"]
    assert not [e for e in evts if e["type"] == "confirm"]
    assert record(applicant["id"], applicant["manual"])["deadline"] is None


def test_a_date_counts_when_the_applicant_wrote_it_earlier_in_the_same_conversation_only(propose, applicant):
    when = future(101)
    propose("search_programs", keyword="x")
    ask(applicant["client"], f"先记着，我那个手动申请的截止日期是 {when.month} 月 {when.day} 日", conversation="c1")
    propose("propose_application_deadline", application_id=applicant["manual"], stated_deadline=when.isoformat())

    # Another conversation never heard the date.
    elsewhere = ask(applicant["client"], "把手动加的那个申请的截止日期填上", conversation="c2")
    assert last(elsewhere, opened(elsewhere, "propose_application_deadline")["id"])["status"] == "failed"

    here = ask(applicant["client"], "好，现在把它填进去", conversation="c1")
    assert confirm_of(here)["changes"][0] == {"label": "截止日期", "before": None, "after": when.isoformat()}


# ---------------------------------------------------------------------------------------------------
# One account cannot reach another's applications
# ---------------------------------------------------------------------------------------------------


def test_another_account_s_application_is_no_application_to_the_stream(propose, applicant):
    stranger = TestClient(app)
    stranger.cookies.set(COOKIE_NAME, new_applicant())
    before = all_records(applicant["id"])
    propose("propose_application_status", application_id=applicant["manual"], status="excluded")

    evts = ask(stranger, "把这个申请标成已放弃")

    start = opened(evts, "propose_application_status")
    # The id is shown as the model wrote it: it does not resolve to the other account's school.
    assert start["args"][0] == {"label": "申请", "value": applicant["manual"]}
    closed = last(evts, start["id"])
    assert closed["status"] == "failed" and "没有这个申请" in closed["result"]
    # The reason is the applicant's line; how to call the tool is for the model and stays out of it.
    assert closed["result"] == "没有执行：没有这个申请。"
    assert not [e for e in evts if e["type"] == "confirm"]
    assert "Example" not in json.dumps(evts, ensure_ascii=False)
    assert all_records(applicant["id"]) == before


def test_another_account_cannot_answer_the_card(propose, applicant):
    propose("propose_application_status", application_id=applicant["manual"], status="submitted")
    card = confirm_of(ask(applicant["client"], "标成已提交"))
    stranger = TestClient(app)
    stranger.cookies.set(COOKIE_NAME, new_applicant())

    assert errors(answer(stranger, card)) == [NOTHING_PENDING]
    assert record(applicant["id"], applicant["manual"])["status"] == "considering"
    assert "已执行" in said(answer(applicant["client"], card))


# ---------------------------------------------------------------------------------------------------
# A stale version
# ---------------------------------------------------------------------------------------------------


def test_a_card_answered_after_the_record_moved_writes_nothing_and_says_what_moved(propose, applicant):
    key, client_id = applicant["manual"], applicant["id"]
    propose("propose_application_status", application_id=key, status="submitted")
    evts = ask(applicant["client"], "标成已提交")
    start, card = opened(evts, "propose_application_status"), confirm_of(evts)
    # Another device edits the record while the card waits.
    with SessionLocal() as s:
        base = records.read_record(s, client_id, key)["version"]
        records.update_record(s, client_id, key, RecordPatch(round="Round 3", base_version=base))
    moved = version_of(key)

    replied = answer(applicant["client"], card)

    assert last(replied, start["id"])["result"] == steps.CONFIRMED
    write = last(replied, f"{start['id']}:write")
    assert write["status"] == "failed" and "write" not in write
    assert write["result"].startswith("没有执行：别处改过了（轮次：未填 → Round 3）")
    assert "这次没有写入" in said(replied)
    stored = record(client_id, key)
    assert stored["status"] == "considering" and stored["round"] == "Round 3"
    assert version_of(key) == moved, "the stale answer wrote nothing"


# ---------------------------------------------------------------------------------------------------
# Exactly once
# ---------------------------------------------------------------------------------------------------


def test_a_confirm_after_a_restart_writes_the_change_once(propose, service, applicant):
    key = applicant["manual"]
    propose("propose_application_status", application_id=key, status="submitted")
    card = confirm_of(ask(applicant["client"], "标成已提交"))
    before = version_of(key)

    service.restart()
    replied = answer(applicant["client"], card)

    assert "已执行" in said(replied) and version_of(key) == before + 1
    service.restart()
    assert errors(answer(applicant["client"], card)) == [NOTHING_PENDING]
    assert version_of(key) == before + 1 and record(applicant["id"], key)["status"] == "submitted"


def test_an_added_application_confirmed_after_a_restart_is_added_once(propose, service, applicant):
    propose("propose_manual_application", school="Another University", name="MSc Robotics")
    card = confirm_of(ask(applicant["client"], "手动加一个申请"))
    before = manual_rows(applicant["id"])

    service.restart()
    assert "已执行" in said(answer(applicant["client"], card))
    service.restart()
    assert errors(answer(applicant["client"], card)) == [NOTHING_PENDING]
    assert manual_rows(applicant["id"]) == before + 1


def at_once(subject: str, *bodies: dict) -> list[list[dict]]:
    """Send the confirms together on one event loop and return each one's events."""

    async def both() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={COOKIE_NAME: subject}) as c:
            return await asyncio.gather(*(c.post(CONFIRM, json=body) for body in bodies))

    return [events(r) for r in asyncio.run(both())]


def test_two_confirms_of_one_card_at_once_write_the_change_once(propose, applicant):
    """A double click, or the same card answered in two tabs: one resumes, the other is told to wait."""
    key = applicant["manual"]
    model = propose("propose_application_status", application_id=key, status="submitted")
    card = confirm_of(ask(applicant["client"], "标成已提交"))
    before = version_of(key)
    model.delay = 0.5
    body = {"conversationId": "c1", "approved": True, "interruptId": card["id"]}

    replies = at_once(applicant["id"], body, body)

    assert sorted("已执行" in said(r) for r in replies) == [False, True], replies
    loser = next(r for r in replies if "已执行" not in said(r))
    assert errors(loser) in (["这个操作正在处理，请稍候。"], [NOTHING_PENDING])
    assert version_of(key) == before + 1


def test_two_cards_drawn_from_one_version_confirmed_at_once_accept_exactly_one(propose, applicant):
    """Two conversations each hold a card for the same record, both drawn from the same version, and
    both are confirmed at the same moment. The thread lock does not separate them (they are different
    threads); the record's version does. One is written, the other is told the record moved."""
    key, client_id = applicant["manual"], applicant["id"]
    pairs = [("submitted", "applying"), ("offered", "rejected")]
    for round_no in range(ROUNDS):
        first, second = pairs[round_no % 2]
        propose(by_message={
            "甲": ("propose_application_status", {"application_id": key, "status": first}),
            "乙": ("propose_application_status", {"application_id": key, "status": second}),
        })
        cards = {
            f"a{round_no}": confirm_of(ask(applicant["client"], "甲", conversation=f"a{round_no}")),
            f"b{round_no}": confirm_of(ask(applicant["client"], "乙", conversation=f"b{round_no}")),
        }
        before = version_of(key)

        replies = at_once(client_id, *(
            {"conversationId": conversation, "approved": True, "interruptId": card["id"]}
            for conversation, card in cards.items()
        ))

        texts = [said(r) for r in replies]
        assert sorted("已执行" in t for t in texts) == [False, True], f"round {round_no}: {texts}"
        refused = next(t for t in texts if "已执行" not in t)
        assert "别处改过了" in refused and "这次没有写入" in refused, f"round {round_no}: {refused}"
        assert version_of(key) == before + 1, f"round {round_no}: one write"
        winner = first if "已执行" in texts[0] else second
        assert record(client_id, key)["status"] == winner, f"round {round_no}: the stored status is the accepted one"


CHILD = textwrap.dedent(
    """
    import asyncio, json, os, signal, sys
    from langchain_core.messages import HumanMessage
    from langgraph.types import Command
    from app.agent import graph as graph_module, intent
    from app.agent.checkpoint import Checkpointer
    from app.config import settings
    from app.services import application_records as records
    from tests.test_advisor_application_tools import Proposes

    step, subject, tool, arguments = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4])
    settings.chat_api_key = "test-key"
    graph_module.get_chat_model = lambda **kwargs: Proposes(tool=tool, arguments=arguments)

    async def operation(query, history):
        return {"intent": "业务操作", "confidence": 1.0}

    intent.classify = operation
    config = {"configurable": {"thread_id": subject + ":c1", "client_id": subject}}
    graph = graph_module.build_graph(checkpointer=Checkpointer())

    def then_die(real):
        def wrapped(*args, **kwargs):
            real(*args, **kwargs)                    # the write is committed
            os.kill(os.getpid(), signal.SIGKILL)     # and the process dies before the step is checkpointed
        return wrapped

    async def main():
        if step == "pause":
            out = await graph.ainvoke({"messages": [HumanMessage(content="改一下")], "trace": None}, config,
                                      durability="sync")
            print(json.dumps({"paused": [i.id for i in out["__interrupt__"]]}), flush=True)
            return
        state = await graph.aget_state(config)
        if not state.interrupts:
            print(json.dumps({"pending": False}), flush=True)
            return
        question = state.interrupts[0].value
        answer = {"approved": True, "changes": question["changes"]}
        if "base" in question:
            answer["base"] = question["base"]
        if step == "write-then-die":
            records.update_record = then_die(records.update_record)
            records.create_record = then_die(records.create_record)
        out = await graph.ainvoke(Command(resume=answer), config, durability="sync")
        print(json.dumps({"pending": True, "reply": out["messages"][-1].content}), flush=True)

    asyncio.run(main())
    """
)


def child(step: str, subject: str, tool: str, arguments: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(API_DIR)}
    return subprocess.run(
        [sys.executable, "-c", CHILD, step, subject, tool, json.dumps(arguments)],
        cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


def test_a_process_killed_after_the_write_does_not_write_again_when_the_card_is_answered_again(applicant):
    """Three real processes. The second confirms, commits the write and is killed with SIGKILL before the
    step's checkpoint is saved, so the thread still holds the card. The third answers it again."""
    key, client_id = applicant["manual"], applicant["id"]
    arguments = {"application_id": key, "status": "submitted"}
    before = version_of(key)
    try:
        first = child("pause", client_id, "propose_application_status", arguments)
        assert first.returncode == 0 and json.loads(first.stdout)["paused"], first.stderr
        assert version_of(key) == before

        second = child("write-then-die", client_id, "propose_application_status", arguments)
        assert second.returncode == -signal.SIGKILL, second.stderr
        assert second.stdout == "", "the process died before it could report"
        assert version_of(key) == before + 1 and record(client_id, key)["status"] == "submitted"

        third = child("resume", client_id, "propose_application_status", arguments)
        assert third.returncode == 0, third.stderr
        again = json.loads(third.stdout)
        # The card was still waiting: the kill came before the checkpoint that would have closed it.
        assert again["pending"] is True
        assert "未执行" in again["reply"] and "已经是已提交" in again["reply"]
        assert version_of(key) == before + 1, "the second answer wrote nothing"

        assert json.loads(child("resume", client_id, "propose_application_status", arguments).stdout) == {"pending": False}
    finally:
        with SessionLocal() as s:
            delete_subject(s, client_id)


def test_an_application_added_by_a_process_killed_after_the_write_is_not_added_twice(applicant):
    client_id = applicant["id"]
    arguments = {"school": "Another University", "name": "MSc Robotics"}
    before = manual_rows(client_id)
    try:
        assert json.loads(child("pause", client_id, "propose_manual_application", arguments).stdout)["paused"]
        second = child("write-then-die", client_id, "propose_manual_application", arguments)
        assert second.returncode == -signal.SIGKILL, second.stderr
        assert manual_rows(client_id) == before + 1

        third = child("resume", client_id, "propose_manual_application", arguments)
        assert third.returncode == 0, third.stderr
        again = json.loads(third.stdout)
        assert again["pending"] is True
        assert "已生效" in again["reply"] and "没有重复写入" in again["reply"]
        assert manual_rows(client_id) == before + 1, "the same call asked for the same record"
    finally:
        with SessionLocal() as s:
            delete_subject(s, client_id)


# ---------------------------------------------------------------------------------------------------
# The rules of the stream that the new tools join
# ---------------------------------------------------------------------------------------------------


def test_every_tool_that_writes_an_application_asks_first():
    assert CONFIRMED_TOOLS == {
        "propose_portfolio_change", "propose_manual_application", "propose_application_deadline",
        "propose_application_status", "propose_material_tick",
    }


def test_an_application_change_never_shares_a_step():
    """Beside another call it waits for the next step; two of them are asked one at a time."""
    status = call("propose_application_status", application_id="a", status="submitted")
    material = call("propose_material_tick", application_id="a", ready=True)
    profile = call("update_my_profile", fields_json="{}")

    mixed = one_change_per_step(AIMessage(content="", tool_calls=[profile, status]))
    assert [c["name"] for c in mixed.tool_calls] == ["update_my_profile"]
    two = one_change_per_step(AIMessage(content="", tool_calls=[status, material]))
    assert [c["name"] for c in two.tool_calls] == ["propose_application_status"]


def test_a_change_an_earlier_run_already_wrote_is_a_finished_step_that_did_not_write():
    outcome = steps.call_result(
        "propose_manual_application", ToolMessage(content="已生效：「A B」之前已经加入我的申请，这次没有重复写入。", tool_call_id="c1")
    )
    assert (outcome.status, outcome.result, outcome.write) == ("done", "之前已经写入，这次没有重复写", False)


def test_the_status_tool_offers_every_status_in_the_overview_s_words():
    from app.agent.application_tools import propose_application_status
    from app.agent.confirm import STATUS_LABELS

    for status, label in STATUS_LABELS.items():
        assert f"{status.value} {label}" in propose_application_status.description
    assert list(STATUS_LABELS.values()) == ["考虑中", "准备中", "已提交", "收到录取", "未录取", "已放弃"]
