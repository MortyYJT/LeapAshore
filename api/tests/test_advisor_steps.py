"""The `step` events of the advisor's stream: what the interface draws a turn from.

A turn is a line of stops. Each step opens with `running` and closes under the same id with how it
ended, how long it took and one line of result. These tests run the real graph and the real tools
through the endpoints, with a scripted model, and read the events off the stream.
"""

import asyncio
import json
import uuid
from collections.abc import Callable

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from sqlalchemy import select

from app.agent import graph as graph_module
from app.agent import halt, intent, steps, tools
from app.agent.graph import build_graph, should_continue
from app.config import settings
from app.db import SessionLocal
from app.deps import COOKIE_NAME, load_or_create_profile
from app.main import app
from app.models.application import Application
from app.models.program import Program
from app.routers import advisor
from app.seed import seed_programs
from app.seed_catalog import seed_catalog

pytestmark = pytest.mark.usefixtures("require_db")

CHAT, CONFIRM, STOP = "/api/advisor/chat", "/api/advisor/confirm", "/api/advisor/stop"
USAGE = {"input_tokens": 40, "output_tokens": 2, "total_tokens": 42}


class Scripted(BaseChatModel):
    """Replies with whatever `script` returns for the messages so far. `gate`, when set, is awaited
    before the reply, and `entered` is set once a call is waiting on it."""

    script: Callable[[list], AIMessage]
    gate: asyncio.Event | None = None
    entered: asyncio.Event | None = None

    @property
    def _llm_type(self) -> str:
        return "scripted-steps"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self.script(messages)
        return ChatResult(generations=[ChatGeneration(message=reply.model_copy(update={"usage_metadata": USAGE}))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if self.gate is not None:
            if self.entered is not None:
                self.entered.set()
            await self.gate.wait()
        reply = self.script(messages)
        calls = [{"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                 for i, c in enumerate(reply.tool_calls)]
        chunk = AIMessageChunk(content=reply.content, tool_call_chunks=calls, usage_metadata=USAGE)
        if run_manager and reply.content:
            await run_manager.on_llm_new_token(reply.content, chunk=ChatGenerationChunk(message=chunk))
        yield ChatGenerationChunk(message=chunk)


def call(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": f"call-{uuid.uuid4().hex[:8]}"}


def then_say(first_calls: list[dict], text: str = "好的。") -> Callable[[list], AIMessage]:
    """Ask for `first_calls` on the applicant's message, and say `text` once they are answered."""

    def script(messages):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content=text)
        return AIMessage(content="", tool_calls=first_calls)

    return script


@pytest.fixture
def program() -> Program:
    with SessionLocal() as s:
        # A fresh database (CI) has no programs until the seeds run; they are idempotent.
        seed_programs(s)
        seed_catalog(s)
        row = s.scalars(select(Program).order_by(Program.id).limit(1)).one()
        _ = row.university.name
        s.expunge_all()
        return row


@pytest.fixture
def advisor_with(monkeypatch):
    """Run the advisor on a scripted model, with the intent fixed, on a checkpointer of its own."""
    from app.agent import checkpoint

    saver = checkpoint.Checkpointer()
    monkeypatch.setattr(advisor, "graph", build_graph(checkpointer=saver))
    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(settings, "advisor_subject_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1000/60")

    def use(script, *, route: str = "业务操作") -> Scripted:
        model = Scripted(script=script)

        async def fixed(query, history):
            return {"intent": route, "confidence": 1.0}

        monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: model)
        monkeypatch.setattr(intent, "classify", fixed)
        return model

    yield use
    saver.close()
    advisor._running.clear()
    halt._requested.clear()


def events(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def ask(client: TestClient, message: str = "帮我看看", conversation: str = "c1") -> list[dict]:
    response = client.post(CHAT, json={"conversationId": conversation, "message": message})
    assert response.status_code == 200
    return events(response)


def step_events(evts: list[dict]) -> list[dict]:
    return [e for e in evts if e["type"] == "step"]


def life(evts: list[dict], step_id: str) -> list[str]:
    return [e["status"] for e in step_events(evts) if e["id"] == step_id]


def last(evts: list[dict], step_id: str) -> dict:
    return [e for e in step_events(evts) if e["id"] == step_id][-1]


def opened(evts: list[dict], name: str) -> dict:
    return next(e for e in step_events(evts) if e.get("name") == name and e["status"] == "running")


# ---------------------------------------------------------------------------------------------------
# A tool call
# ---------------------------------------------------------------------------------------------------


def test_a_turn_opens_with_the_intent_step_and_every_step_it_opens_is_closed(advisor_with, program):
    advisor_with(then_say([call("search_programs", keyword=program.name)]))
    evts = ask(TestClient(app))

    first = evts[0]
    assert first["type"] == "step" and first["kind"] == "intent" and first["status"] == "running"
    assert first["name"] == "classify_intent" and first["title"] == "判断问题类型"
    closed = last(evts, first["id"])
    assert closed["status"] == "done" and closed["result"] == "归为「修改申请」，交给顾问处理"
    assert isinstance(closed["ms"], int) and closed["ms"] >= 0

    for step in step_events(evts):
        assert life(evts, step["id"])[0] == "running"
        assert life(evts, step["id"])[-1] != "running", step
    assert evts[-1] == {"type": "done"}


def test_a_tool_call_is_a_step_with_its_arguments_and_a_one_line_result(advisor_with, program):
    advisor_with(then_say([call("search_programs", keyword=program.name)], "找到了。"))
    evts = ask(TestClient(app))

    start = opened(evts, "search_programs")
    assert start["kind"] == "tool" and start["title"] == "搜索项目"
    assert start["args"] == [{"label": "关键词", "value": program.name}]
    end = last(evts, start["id"])
    assert end["status"] == "done" and end["result"].startswith("找到 ") and end["ms"] >= 0
    assert any(program.name in item for item in end["items"])
    # The step closes before the model's next words, and the events the page read before are still sent.
    kinds = [e["type"] for e in evts]
    assert kinds.index("tool") > kinds.index("intent")
    assert evts.index(end) < next(i for i, e in enumerate(evts) if e["type"] == "token")
    assert "".join(e["text"] for e in evts if e["type"] == "token") == "找到了。"


def test_reading_the_applicant_s_own_data_reports_counts_and_no_values(advisor_with):
    client = TestClient(app)
    client.post(CHAT, json={"conversationId": "warm", "message": "hi"})  # mints the cookie
    subject = client.cookies.get(COOKIE_NAME)
    with SessionLocal() as s:
        profile = load_or_create_profile(s, subject)
        profile.school_name = "某某大学"
        profile.english_score = "IELTS 7.5"
        s.commit()
    advisor_with(then_say([call("get_my_profile"), call("get_my_applications"), call("get_my_portfolio")]))
    evts = ask(client)

    profile_step = last(evts, opened(evts, "get_my_profile")["id"])
    assert profile_step["status"] == "done" and profile_step["result"].startswith("已填 2 项")
    assert last(evts, opened(evts, "get_my_applications")["id"])["status"] == "empty"
    assert last(evts, opened(evts, "get_my_portfolio")["id"])["result"] == "组合里还没有项目"
    stream = json.dumps(step_events(evts), ensure_ascii=False)
    assert "某某大学" not in stream and "IELTS" not in stream


def test_a_profile_update_shows_what_was_written_and_is_marked_as_a_write(advisor_with):
    advisor_with(then_say([call("update_my_profile", fields_json=json.dumps({"major": "统计学", "gpa_score": 88}))]))
    evts = ask(TestClient(app), "我是统计学专业，均分 88")

    start = opened(evts, "update_my_profile")
    assert start["write"] is True
    assert start["args"] == [{"label": "专业", "value": "统计学"}, {"label": "均分", "value": "88"}]
    end = last(evts, start["id"])
    assert end["status"] == "done" and end["result"] == "已保存 2 项" and end["write"] is True


def test_a_tool_the_interface_has_never_heard_of_is_still_a_step():
    """A tool added later needs no change in the page: its name, its arguments cut short, a plain outcome."""
    assert steps.title("set_application_deadline") is None
    args = steps.call_args("set_application_deadline", {"application_id": "a1", "deadline": "2027-01-15", "note": "x" * 200})
    assert args[:2] == [{"label": "application_id", "value": "a1"}, {"label": "deadline", "value": "2027-01-15"}]
    assert len(args[2]["value"]) == 80 and args[2]["value"].endswith("…")

    def reply(content: str) -> ToolMessage:
        return ToolMessage(content=content, tool_call_id="c1")

    saved = steps.call_result("set_application_deadline", reply("已执行：把截止日期改为 2027-01-15"))
    assert (saved.status, saved.result, saved.write) == ("done", "已保存", True)
    refused = steps.call_result("set_application_deadline", reply("未执行：没有这个申请。"))
    assert (refused.status, refused.result) == ("failed", "没有执行：没有这个申请。")
    rows = steps.call_result("list_my_documents", reply(json.dumps([{"secret": "成绩单内容"}])))
    assert (rows.status, rows.result) == ("done", "返回 1 条") and rows.items == []
    assert steps.call_result("anything", reply("一段不认识的输出，里面可能有个人信息")).result == "已完成"


# ---------------------------------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------------------------------


def test_a_tool_that_breaks_closes_its_step_as_failed_before_the_error(advisor_with, program, monkeypatch):
    def broken(session, keyword):
        raise RuntimeError("database fell over")

    monkeypatch.setattr(tools, "_search_by_school", broken)
    advisor_with(then_say([call("search_programs", keyword="x")]))
    evts = ask(TestClient(app))

    start = opened(evts, "search_programs")
    assert life(evts, start["id"]) == ["running", "failed"]
    error = next(e for e in evts if e["type"] == "error")
    assert error["code"] == "advisor_failed"
    assert evts.index(last(evts, start["id"])) < evts.index(error)
    assert "database fell over" not in json.dumps(evts, ensure_ascii=False)
    assert evts[-1] == {"type": "done"}


def test_the_provider_going_down_after_a_tool_keeps_the_tool_s_step_done(advisor_with, program):
    def script(messages):
        if isinstance(messages[-1], ToolMessage):
            request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
            raise openai.APIStatusError("Insufficient Balance", response=httpx.Response(402, request=request), body=None)
        return AIMessage(content="", tool_calls=[call("search_programs", keyword=program.name)])

    advisor_with(script)
    evts = ask(TestClient(app))

    assert life(evts, opened(evts, "search_programs")["id"]) == ["running", "done"]
    assert [e["code"] for e in evts if e["type"] == "error"] == ["model_unavailable"]


def test_a_refused_tool_call_is_a_failed_step_with_the_tool_s_reason(advisor_with):
    advisor_with(then_say([call("propose_portfolio_change", program_id="no-such-program", action="add", tier="稳")]))
    evts = ask(TestClient(app))

    end = last(evts, opened(evts, "propose_portfolio_change")["id"])
    assert end["status"] == "failed" and end["result"] == "没有执行：没有 id 为 no-such-program 的项目。"
    assert not [e for e in evts if e["type"] == "confirm"]


def test_an_unconfigured_model_is_its_own_error(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "")
    evts = ask(TestClient(app))
    assert [e.get("code") for e in evts if e["type"] == "error"] == ["not_configured"]
    assert step_events(evts) == []


# ---------------------------------------------------------------------------------------------------
# Interrupt and confirm
# ---------------------------------------------------------------------------------------------------


def propose(program_id: str, **args) -> Callable[[list], AIMessage]:
    def script(messages):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content=f"好的。{messages[-1].content}")
        return AIMessage(content="", tool_calls=[call("propose_portfolio_change", program_id=program_id, **args)])

    return script


def answer(client: TestClient, confirm: dict, approved: bool) -> list[dict]:
    body = {"conversationId": "c1", "approved": approved, "interruptId": confirm["id"]}
    response = client.post(CONFIRM, json=body)
    assert response.status_code == 200
    return events(response)


def portfolio(subject: str) -> list[tuple[str, str, str]]:
    with SessionLocal() as s:
        rows = s.scalars(select(Application).where(Application.client_id == subject))
        return sorted((r.program_id, r.tier, r.status) for r in rows)


def test_a_proposed_change_waits_as_a_step_and_says_exactly_what_it_changes(advisor_with, program):
    advisor_with(propose(program.id, action="add", tier="冲"))
    client = TestClient(app)
    evts = ask(client, "把这个项目加入选校")

    start = opened(evts, "propose_portfolio_change")
    name = f"{program.university.name} {program.name}"
    assert start["args"] == [{"label": "项目", "value": name}, {"label": "操作", "value": "加入组合"},
                             {"label": "档位", "value": "冲"}]
    waiting = last(evts, start["id"])
    assert waiting["status"] == "waiting" and waiting["result"] == "等你确认"

    confirm = next(e for e in evts if e["type"] == "confirm")
    assert confirm["stepId"] == start["id"] and confirm["kind"] == "confirm_portfolio" and confirm["id"]
    assert confirm["target"] == {"programId": program.id, "school": program.university.name, "program": program.name}
    assert confirm["changes"] == [
        {"label": "选校组合", "before": "不在组合里", "after": "加入"},
        {"label": "档位", "before": None, "after": "冲"},
        {"label": "申请状态", "before": None, "after": "考虑中"},
    ]
    assert evts.index(waiting) < evts.index(confirm)
    # Nothing is left open, and nothing has been written.
    assert all(life(evts, s["id"])[-1] != "running" for s in step_events(evts))
    assert portfolio(client.cookies.get(COOKIE_NAME)) == []


def test_a_confirmed_change_is_written_in_a_step_of_its_own(advisor_with, program):
    advisor_with(propose(program.id, action="add", tier="稳"))
    client = TestClient(app)
    confirm = next(e for e in ask(client, "把这个项目加入选校") if e["type"] == "confirm")

    evts = answer(client, confirm, approved=True)
    write = f"{confirm['stepId']}:write"
    first = evts[0]
    assert first == {"type": "step", "id": write, "status": "running", "kind": "tool",
                     "name": "propose_portfolio_change", "title": "写入", "write": True}
    assert last(evts, confirm["stepId"]) == {"type": "step", "id": confirm["stepId"], "status": "done", "result": "你已确认"}
    written = last(evts, write)
    assert written["status"] == "done" and written["result"] == "已保存" and written["write"] is True and written["ms"] >= 0
    assert portfolio(client.cookies.get(COOKIE_NAME)) == [(program.id, "稳", "considering")]
    assert "已执行" in "".join(e["text"] for e in evts if e["type"] == "token")


def test_a_declined_change_closes_the_proposal_and_writes_nothing(advisor_with, program):
    advisor_with(propose(program.id, action="add", tier="稳"))
    client = TestClient(app)
    confirm = next(e for e in ask(client, "把这个项目加入选校") if e["type"] == "confirm")

    evts = answer(client, confirm, approved=False)
    assert [e["id"] for e in step_events(evts)] == [confirm["stepId"]]
    assert last(evts, confirm["stepId"])["status"] == "declined"
    assert last(evts, confirm["stepId"])["result"] == "已取消，没有改动"
    assert portfolio(client.cookies.get(COOKIE_NAME)) == []


def test_a_change_to_a_program_already_in_the_portfolio_shows_the_values_it_replaces(advisor_with, program):
    client = TestClient(app)
    advisor_with(propose(program.id, action="add", tier="稳"))
    answer(client, next(e for e in ask(client, "加入") if e["type"] == "confirm"), approved=True)

    advisor_with(propose(program.id, action="set_status", status="submitted"))
    confirm = next(e for e in ask(client, "标成已提交") if e["type"] == "confirm")
    assert confirm["changes"] == [{"label": "申请状态", "before": "考虑中", "after": "已提交"}]
    answer(client, confirm, approved=True)

    # Adding it again would put the status back; the question says so before anything is written.
    advisor_with(propose(program.id, action="add", tier="冲"))
    again = next(e for e in ask(client, "改成冲刺") if e["type"] == "confirm")
    assert again["changes"] == [
        {"label": "档位", "before": "稳", "after": "冲"},
        {"label": "申请状态", "before": "已提交", "after": "考虑中"},
    ]

    advisor_with(propose(program.id, action="remove"))
    answer(client, again, approved=False)
    gone = next(e for e in ask(client, "移出") if e["type"] == "confirm")
    assert gone["changes"] == [{"label": "选校组合", "before": "在组合里（稳，已提交）", "after": "移出"}]


# ---------------------------------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------------------------------


def test_the_loop_ends_instead_of_running_a_tool_once_a_stop_is_asked():
    state = {"messages": [AIMessage(content="", tool_calls=[call("update_my_profile", fields_json="{}")])], "steps": 1}
    config = {"configurable": {"thread_id": "s:t"}}
    assert should_continue(state, config) == "continue"
    halt.request("s:t")
    try:
        assert should_continue(state, config) == "stop"
        assert graph_module.route_by_intent({"intent": "规划"}, config) == "halt"
        assert graph_module.evidence_gate({"evidence_strong": True}, config) == "halt"
        assert graph_module.after_tools({}, config) == "halt"
        assert should_continue(state, {"configurable": {"thread_id": "other"}}) == "continue"
    finally:
        halt.clear("s:t")
    assert graph_module.after_tools({}, config) == "continue"


def run_async(coroutine):
    return asyncio.run(coroutine)


def hold(model: Scripted) -> None:
    """Give the model a gate, open for now. Called inside the loop the turn runs on."""
    model.gate, model.entered = asyncio.Event(), asyncio.Event()
    model.gate.set()


def test_a_stop_mid_run_ends_the_turn_before_the_tool_the_model_asked_for(advisor_with):
    """The model call in flight finishes (and is charged); the profile update it asked for never runs."""
    model = advisor_with(lambda messages: AIMessage(content="你好。"))

    async def scenario():
        hold(model)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            warm = await c.post(CHAT, json={"conversationId": "warm", "message": "hi"})  # mints the cookie
            model.script = then_say([call("update_my_profile", fields_json=json.dumps({"major": "不该写入"}))])
            model.entered.clear()
            model.gate.clear()
            turn = asyncio.create_task(c.post(CHAT, json={"conversationId": "c1", "message": "我换专业了"}))
            await asyncio.wait_for(model.entered.wait(), 5)
            stopping = await c.post(STOP, json={"conversationId": "c1"})
            model.gate.set()
            first = await turn
            # The stop was for that turn only: the next message on the thread runs to its end.
            model.script = lambda messages: AIMessage(content="继续。")
            second = await c.post(CHAT, json={"conversationId": "c1", "message": "接着说"})
            idle = await c.post(STOP, json={"conversationId": "c1"})
            return warm, stopping, first, second, idle, c.cookies.get(COOKIE_NAME)

    warm, stopping, first, second, idle, subject = run_async(scenario())
    assert stopping.json() == {"stopping": True}
    evts = events(first)
    start = opened(evts, "update_my_profile")
    assert life(evts, start["id"]) == ["running", "stopped"]
    assert last(evts, start["id"])["result"] == "已停止，没有执行"
    assert [e for e in evts if e["type"] == "stopped"] == [{"type": "stopped", "wrote": False}]
    assert evts[-1] == {"type": "done"}
    with SessionLocal() as s:
        assert load_or_create_profile(s, subject).major is None

    assert "".join(e["text"] for e in events(second) if e["type"] == "token") == "继续。"
    assert not [e for e in events(second) if e["type"] in ("stopped", "error")]
    assert idle.json() == {"stopping": False}
    assert advisor._running == {} and not halt.requested(f"{subject}:c1")


def test_a_new_message_waits_for_the_turn_before_it_to_stop(advisor_with):
    """Two turns never run on one thread: the second asks the first to stop and starts when it has."""
    model = advisor_with(lambda messages: AIMessage(content="答完了。"))

    async def scenario():
        hold(model)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            await c.post(CHAT, json={"conversationId": "warm", "message": "hi"})  # mints the cookie
            model.entered.clear()
            model.gate.clear()
            first = asyncio.create_task(c.post(CHAT, json={"conversationId": "c1", "message": "第一句"}))
            await asyncio.wait_for(model.entered.wait(), 5)
            second = asyncio.create_task(c.post(CHAT, json={"conversationId": "c1", "message": "第二句"}))
            await asyncio.sleep(0.2)
            waited = not second.done() and halt.requested(f"{c.cookies.get(COOKIE_NAME)}:c1")
            model.gate.set()
            return waited, await first, await second

    waited, first, second = run_async(scenario())
    assert waited
    assert [e["type"] for e in events(first)][-2:] == ["stopped", "done"]
    assert not [e for e in events(second) if e["type"] in ("stopped", "error")]
    assert "".join(e["text"] for e in events(second) if e["type"] == "token") == "答完了。"


def test_a_message_is_told_to_wait_when_the_turn_before_it_does_not_stop_in_time(advisor_with, monkeypatch):
    model = advisor_with(lambda messages: AIMessage(content="答完了。"))
    monkeypatch.setattr(advisor, "TAKE_OVER_SECONDS", 0.2)

    async def scenario():
        hold(model)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            await c.post(CHAT, json={"conversationId": "warm", "message": "hi"})  # mints the cookie
            model.entered.clear()
            model.gate.clear()
            first = asyncio.create_task(c.post(CHAT, json={"conversationId": "c1", "message": "第一句"}))
            await asyncio.wait_for(model.entered.wait(), 5)
            second = await c.post(CHAT, json={"conversationId": "c1", "message": "第二句"})
            model.gate.set()
            await first
            return second

    second = run_async(scenario())
    assert events(second) == [{"type": "error", "code": "busy", "message": advisor.BUSY}, {"type": "done"}]


# ---------------------------------------------------------------------------------------------------
# Retrieval and citations
# ---------------------------------------------------------------------------------------------------


def test_a_requirement_question_retrieves_in_a_step_and_names_what_it_found(advisor_with, monkeypatch):
    from app.agent import evidence

    cited = {"n": 1, "programId": "p1", "program": "甲大学 数据科学硕士", "title": "MSc Data Science",
             "url": "https://example.edu/msc", "status": "待核验", "fields": [{"label": "语言", "value": "IELTS 6.5"}]}
    found = {"evidence_strong": True, "evidence": "[1] 甲大学 数据科学硕士", "citations": [cited],
             "trace": {"evidence_gate": "strong", "gate_signals": {}}}
    monkeypatch.setattr(evidence, "gate", lambda session, query: found)
    advisor_with(lambda messages: AIMessage(content="语言要求是 IELTS 6.5 [1]。"), route="官方要求核验")
    evts = ask(TestClient(app), "甲大学数据科学硕士的语言要求？")

    start = opened(evts, "retrieve_requirements")
    assert start["kind"] == "retrieval" and start["title"] == "检索学校库"
    end = last(evts, start["id"])
    assert end["status"] == "done" and end["result"] == "找到 1 个有官方来源的项目" and end["items"] == ["甲大学 数据科学硕士"]
    citations = next(e for e in evts if e["type"] == "citations")
    assert citations["gate"] == "pass" and citations["citations"] == [cited]
    assert evts.index(end) < evts.index(citations) < next(i for i, e in enumerate(evts) if e["type"] == "token")


def test_a_retrieval_that_finds_nothing_citable_is_an_empty_step_and_a_refusal(advisor_with, monkeypatch):
    from app.agent import evidence
    from app.services import knowledge_gaps

    weak = {"evidence_strong": False, "refusal": "no_school", "refusal_text": "这所学校还没有收录，我不能凭印象回答。",
            "citations": [], "trace": {"evidence_gate": "weak", "gate_signals": {}}}
    monkeypatch.setattr(evidence, "gate", lambda session, query: weak)
    monkeypatch.setattr(knowledge_gaps, "record_safely", lambda **kwargs: None)
    advisor_with(lambda messages: AIMessage(content="不该被调用"), route="官方要求核验")
    evts = ask(TestClient(app), "某校的要求？")

    end = last(evts, opened(evts, "retrieve_requirements")["id"])
    assert end["status"] == "empty" and end["result"] == "没有可引用的官方来源"
    assert next(e for e in evts if e["type"] == "citations")["gate"] == "refuse"
    assert "".join(e["text"] for e in evts if e["type"] == "token") == weak["refusal_text"]


def test_a_citation_carries_only_what_the_catalogue_holds():
    from datetime import date
    from decimal import Decimal
    from types import SimpleNamespace

    from app.agent import evidence

    source = SimpleNamespace(id="s1", title="MSc CS", url="https://example.edu/msc", verified_at=None)
    deadline = SimpleNamespace(label="Round 2", deadline=date(2027, 1, 15), sort_order=0,
                               quote="Round 2 applications close on 15 January 2027.", source_url="https://example.edu/dates")
    passed = SimpleNamespace(label=None, deadline=date(2026, 1, 1), sort_order=1, quote="", source_url="https://example.edu/msc")
    program = SimpleNamespace(minimum_mark=Decimal("80.00"), non_211_minimum_mark=None, english_requirement="IELTS 6.5",
                              academic_requirement=None, academic_source_url=None, deadlines=[deadline, passed],
                              prerequisites=[])
    fields = evidence.citation_fields(evidence.Hit(program, source), today=date(2026, 11, 20))
    assert fields == [
        {"label": "均分要求（211/985）", "value": "80"},
        {"label": "语言", "value": "IELTS 6.5"},
        {"label": "申请截止", "value": "Round 2 2027-01-15", "quote": "Round 2 applications close on 15 January 2027.",
         "url": "https://example.edu/dates"},
        {"label": "申请截止", "value": "2026-01-01（已截止）"},
    ]
