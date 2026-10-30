"""The advisor's conversations in Postgres (openspec advisor-persistence).

TASKS.md P1 #3's completion standard: a turn waiting for the applicant's confirm survives a restart of
the service, and the confirmed change is then written correctly and exactly once. "Restart" is tested
two ways: a new checkpointer and graph against the same database inside the test process (through
the real endpoints), and two real Python processes, the first killed with SIGKILL while the turn waits.

The model is scripted: asked anything, it proposes adding one program; shown the tool's answer, it
replies with it. Every model call reports 42 tokens, so the usage accounting (P0 #5) is checked on the
persisted path too.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select, text

from app import limits
from app.agent import checkpoint, intent, tools
from app.agent import graph as graph_module
from app.agent.graph import UNANSWERED_CALL, build_graph, with_unanswered_calls_closed
from app.cleanup import sweep_conversations
from app.config import settings
from app.db import SessionLocal
from app.deps import COOKIE_NAME, load_or_create_profile
from app.main import app
from app.models.application import Application
from app.models.program import Program
from app.routers import advisor
from app.seed import seed_programs
from app.seed_catalog import seed_catalog
from app.services.accounts import delete_subject, merge_subject
from app.services.conversations import threads_of

pytestmark = pytest.mark.usefixtures("require_db")

API_DIR = Path(__file__).resolve().parent.parent
USAGE = {"input_tokens": 40, "output_tokens": 2, "total_tokens": 42}
CHAT = "/api/advisor/chat"
CONFIRM = "/api/advisor/confirm"


class Scripted(BaseChatModel):
    """Proposes adding `program_id` to a human message, and repeats the tool's answer to a tool reply."""

    program_id: str
    delay: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            reply = AIMessage(content=f"好的。{last.content}", usage_metadata=USAGE)
        else:
            call = {
                "name": "propose_portfolio_change",
                "args": {"program_id": self.program_id, "action": "add", "tier": "稳"},
                "id": f"call-{uuid.uuid4().hex[:8]}",
            }
            reply = AIMessage(content="", tool_calls=[call], usage_metadata=USAGE)
        return ChatResult(generations=[ChatGeneration(message=reply)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(self.delay)
        return self._generate(messages, stop, run_manager, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        """One chunk, the way the advisor's streaming model delivers text (and the token events)."""
        await asyncio.sleep(self.delay)
        reply = self._generate(messages).generations[0].message
        calls = [
            {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": 0} for c in reply.tool_calls
        ]
        chunk = AIMessageChunk(content=reply.content, tool_call_chunks=calls, usage_metadata=USAGE)
        if run_manager and reply.content:
            await run_manager.on_llm_new_token(reply.content, chunk=ChatGenerationChunk(message=chunk))
        yield ChatGenerationChunk(message=chunk)


@pytest.fixture
def program_id() -> str:
    with SessionLocal() as s:
        # A fresh database (CI) has no programs until the seeds run; they are idempotent.
        seed_programs(s)
        seed_catalog(s)
        return s.scalars(select(Program.id).order_by(Program.id).limit(1)).one()


@pytest.fixture
def model(monkeypatch, program_id) -> Scripted:
    scripted = Scripted(program_id=program_id)

    async def operation(query, history):
        return {"intent": "业务操作", "confidence": 1.0}

    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: scripted)
    monkeypatch.setattr(intent, "classify", operation)
    monkeypatch.setattr(settings, "advisor_subject_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1000/60")
    return scripted


@pytest.fixture
def writes(monkeypatch) -> list[str]:
    """Every portfolio write the confirm tool makes, by subject."""
    made: list[str] = []
    real = tools.replace_applications

    def counted(session, client_id, rows):
        made.append(client_id)
        return real(session, client_id, rows)

    monkeypatch.setattr(tools, "replace_applications", counted)
    return made


class Service:
    """The API's graph, swapped for one on a checkpointer of its own so the test can "restart" it."""

    def __init__(self, monkeypatch) -> None:
        self.monkeypatch = monkeypatch
        self.savers: list[checkpoint.Checkpointer] = []
        self.start()

    def start(self) -> None:
        saver = checkpoint.Checkpointer()
        self.savers.append(saver)
        self.monkeypatch.setattr(advisor, "graph", build_graph(checkpointer=saver))

    def restart(self) -> None:
        """Drop everything the running service held in memory and start again on the same database."""
        self.savers[-1].close()
        self.start()

    def close(self) -> None:
        for saver in self.savers:
            saver.close()


@pytest.fixture
def service(monkeypatch):
    running = Service(monkeypatch)
    yield running
    running.close()


def events(response) -> list[dict]:
    return [json.loads(line[len("data: ") :]) for line in response.text.splitlines() if line.startswith("data: ")]


def portfolio(subject: str) -> list[tuple[str, str]]:
    with SessionLocal() as s:
        rows = s.scalars(select(Application).where(Application.client_id == subject))
        return sorted((r.program_id, r.tier) for r in rows)


def checkpoint_rows(thread: str) -> int:
    with SessionLocal() as s:
        return s.scalar(text("SELECT count(*) FROM checkpoints WHERE thread_id = :t"), {"t": thread})


def pause(client: TestClient, conversation: str = "c1") -> dict:
    """Ask for the change and return the confirm event the turn stopped on."""
    response = client.post(CHAT, json={"conversationId": conversation, "message": "把这个项目加入选校"})
    assert response.status_code == 200
    confirms = [e for e in events(response) if e["type"] == "confirm"]
    assert len(confirms) == 1, events(response)
    return confirms[0]


def answer(client: TestClient, confirm: dict | None, conversation: str = "c1", approved: bool = True) -> list[dict]:
    body = {"conversationId": conversation, "approved": approved}
    if confirm is not None:
        body["interruptId"] = confirm["id"]
    response = client.post(CONFIRM, json=body)
    assert response.status_code == 200
    return events(response)


def said(evts: list[dict]) -> str:
    return "".join(e.get("text", "") for e in evts if e["type"] == "token")


def errors(evts: list[dict]) -> list[str]:
    return [e["message"] for e in evts if e["type"] == "error"]


# ---------------------------------------------------------------------------------------------------
# The completion standard
# ---------------------------------------------------------------------------------------------------


def test_a_confirm_after_a_restart_writes_the_change_once(service, model, writes, program_id):
    client = TestClient(app)
    confirm = pause(client)
    subject = client.cookies.get(COOKIE_NAME)
    thread = f"{subject}:c1"
    assert confirm["kind"] == "confirm_portfolio" and confirm["id"]
    assert portfolio(subject) == [] and writes == []
    # The turn ended paused and pruned to its latest checkpoint, which still holds the paused change.
    assert checkpoint_rows(thread) == 1

    service.restart()

    replied = answer(client, confirm)
    assert errors(replied) == []
    assert "已执行" in said(replied)
    assert replied[-1] == {"type": "done"}
    assert portfolio(subject) == [(program_id, "稳")]
    assert writes == [subject]

    # The same click again, after another restart: nothing is pending, nothing is written.
    service.restart()
    again = answer(client, confirm)
    assert errors(again) == ["没有待确认的操作，可能已经处理过或已过期。"]
    assert writes == [subject]
    assert portfolio(subject) == [(program_id, "稳")]
    # Two model calls of 42 tokens, one per turn; both reservations were given back.
    assert asyncio.run(limits.usage_today(subject, "testclient")) == {"subject": 84, "ip": 84, "site": 84}


def test_a_declined_change_after_a_restart_writes_nothing(service, model, writes):
    client = TestClient(app)
    confirm = pause(client)
    service.restart()
    replied = answer(client, confirm, approved=False)
    assert "用户取消了操作" in said(replied)
    assert writes == [] and portfolio(client.cookies.get(COOKIE_NAME)) == []


CHILD = textwrap.dedent(
    """
    import asyncio, json, os, signal, sys
    from langchain_core.messages import HumanMessage
    from langgraph.types import Command
    from app.agent import graph as graph_module, intent, tools
    from app.agent.checkpoint import Checkpointer
    from app.config import settings
    from tests.test_advisor_persistence import Scripted

    step, subject, program_id = sys.argv[1:4]
    settings.chat_api_key = "test-key"
    graph_module.get_chat_model = lambda **kwargs: Scripted(program_id=program_id)

    async def operation(query, history):
        return {"intent": "业务操作", "confidence": 1.0}

    intent.classify = operation
    made = []
    real = tools.replace_applications
    tools.replace_applications = lambda s, c, rows: made.append(c) or real(s, c, rows)
    config = {"configurable": {"thread_id": subject + ":c1", "client_id": subject}}
    graph = graph_module.build_graph(checkpointer=Checkpointer())

    async def main():
        if step == "pause":
            out = await graph.ainvoke({"messages": [HumanMessage(content="加入")], "trace": None}, config,
                                      durability="sync")
            print(json.dumps({"paused": [i.id for i in out["__interrupt__"]]}), flush=True)
            os.kill(os.getpid(), signal.SIGKILL)  # die holding everything, as a crashed server would
        state = await graph.aget_state(config)
        if not state.interrupts:
            print(json.dumps({"pending": False, "writes": made}), flush=True)
            return
        out = await graph.ainvoke(Command(resume=True), config, durability="sync")
        print(json.dumps({"pending": True, "writes": made, "reply": out["messages"][-1].content}), flush=True)

    asyncio.run(main())
    """
)


def test_a_paused_turn_survives_a_killed_process(program_id):
    """Two real processes: the first pauses the turn and is killed with SIGKILL; the second resumes."""
    subject = str(uuid.uuid4())
    with SessionLocal() as s:
        load_or_create_profile(s, subject)

    def run(step: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONPATH": str(API_DIR)}
        return subprocess.run(
            [sys.executable, "-c", CHILD, step, subject, program_id],
            cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120,
        )

    try:
        first = run("pause")
        assert first.returncode == -signal.SIGKILL, first.stderr
        assert json.loads(first.stdout)["paused"]
        assert portfolio(subject) == []

        second = run("resume")
        assert second.returncode == 0, second.stderr
        resumed = json.loads(second.stdout)
        assert resumed["pending"] is True and resumed["writes"] == [subject]
        assert "已执行" in resumed["reply"]
        assert portfolio(subject) == [(program_id, "稳")]

        third = run("resume")
        assert json.loads(third.stdout) == {"pending": False, "writes": []}
        assert portfolio(subject) == [(program_id, "稳")]
    finally:
        with SessionLocal() as s:
            delete_subject(s, subject)


def test_two_confirms_at_once_write_the_change_once(service, model, writes, program_id):
    """A double click, or the same change answered in two tabs: one resumes, the other is told to wait."""
    client = TestClient(app)
    confirm = pause(client)
    subject = client.cookies.get(COOKIE_NAME)
    model.delay = 0.5
    body = {"conversationId": "c1", "approved": True, "interruptId": confirm["id"]}

    async def both() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={COOKIE_NAME: subject}) as c:
            return await asyncio.gather(c.post(CONFIRM, json=body), c.post(CONFIRM, json=body))

    replies = [events(r) for r in asyncio.run(both())]
    outcomes = sorted("已执行" in said(r) for r in replies)
    assert outcomes == [False, True], replies
    loser = next(r for r in replies if "已执行" not in said(r))
    assert errors(loser) in (["这个操作正在处理，请稍候。"], ["没有待确认的操作，可能已经处理过或已过期。"])
    assert writes == [subject]
    assert portfolio(subject) == [(program_id, "稳")]


def test_another_subject_cannot_answer_the_change(service, model, writes, program_id):
    owner, stranger = TestClient(app), TestClient(app)
    confirm = pause(owner)
    owner_id = owner.cookies.get(COOKIE_NAME)
    stranger.get("/api/health")  # no subject cookie yet; the confirm below mints one
    tried = answer(stranger, confirm)
    assert errors(tried) == ["没有待确认的操作，可能已经处理过或已过期。"]
    assert stranger.cookies.get(COOKIE_NAME) != owner_id
    assert writes == []
    # The owner's change is still waiting, and is still the owner's to answer.
    assert "已执行" in said(answer(owner, confirm))
    assert writes == [owner_id] and portfolio(owner_id) == [(program_id, "稳")]


def test_an_answer_naming_another_change_is_not_taken(service, model, writes):
    client = TestClient(app)
    pause(client)
    stale = answer(client, {"id": "a-change-that-is-no-longer-waiting"})
    assert errors(stale) == ["没有待确认的操作，可能已经处理过或已过期。"]
    assert writes == []


# ---------------------------------------------------------------------------------------------------
# A paused change abandoned for a new message
# ---------------------------------------------------------------------------------------------------


def test_an_unanswered_tool_call_is_closed_for_the_model_only():
    call = {"name": "propose_portfolio_change", "args": {}, "id": "c-1"}
    answered = {"name": "get_my_profile", "args": {}, "id": "c-2"}
    history = [
        HumanMessage(content="加入"),
        AIMessage(content="", tool_calls=[call]),
        HumanMessage(content="算了"),
        AIMessage(content="", tool_calls=[answered]),
        ToolMessage(content="{}", tool_call_id="c-2"),
    ]
    out = with_unanswered_calls_closed(history)
    assert [type(m).__name__ for m in out] == [
        "HumanMessage", "AIMessage", "ToolMessage", "HumanMessage", "AIMessage", "ToolMessage"
    ]
    assert out[2].tool_call_id == "c-1" and out[2].content == UNANSWERED_CALL
    assert len(history) == 5  # the stored history is not changed


# ---------------------------------------------------------------------------------------------------
# Conversations follow their subject: deletion, merge, the 90-day sweep
# ---------------------------------------------------------------------------------------------------


def put_thread(subject: str, conversation: str, ts: datetime | None = None) -> str:
    """Store a one-checkpoint thread for `subject`, as a turn would, optionally dated in the past."""
    thread = f"{subject}:{conversation}"
    saver = checkpoint.Checkpointer()
    try:
        cp = empty_checkpoint()
        if ts is not None:
            cp["ts"] = ts.isoformat()
        saver.put(
            {"configurable": {"thread_id": thread, "checkpoint_ns": ""}},
            cp,
            {"source": "input", "step": -1, "parents": {}, "client_id": subject},
            {},
        )
    finally:
        saver.close()
    return thread


def subject_with_profile() -> str:
    subject = str(uuid.uuid4())
    with SessionLocal() as s:
        load_or_create_profile(s, subject)
    return subject


def test_deleting_a_subject_deletes_its_conversations_and_no_one_elses():
    gone, kept = subject_with_profile(), subject_with_profile()
    put_thread(gone, "a")
    put_thread(gone, "b")
    put_thread(kept, "a")
    with SessionLocal() as s:
        assert delete_subject(s, gone)["conversations"] == 2
        assert threads_of(s, gone) == []
        assert threads_of(s, kept) == [f"{kept}:a"]


def test_a_merge_moves_the_conversations_and_the_target_keeps_its_own():
    source, target = subject_with_profile(), subject_with_profile()
    put_thread(source, "only-anonymous")
    put_thread(source, "both")
    put_thread(target, "both")
    with SessionLocal() as s:
        counts = merge_subject(s, source, target)
        s.commit()
        assert counts["conversations"] == 1
        assert threads_of(s, source) == []
        assert threads_of(s, target) == [f"{target}:both", f"{target}:only-anonymous"]
        owner = s.scalar(
            text("SELECT metadata ->> 'client_id' FROM checkpoints WHERE thread_id = :t"),
            {"t": f"{target}:only-anonymous"},
        )
        assert owner == target


def test_conversations_untouched_for_ninety_days_are_swept(monkeypatch):
    from app import worker

    monkeypatch.setattr(settings, "auth_enabled", False)
    subject = str(uuid.uuid4())
    old = put_thread(subject, "old", ts=datetime.now(UTC) - timedelta(days=91))
    recent = put_thread(subject, "recent", ts=datetime.now(UTC) - timedelta(days=89))
    with SessionLocal() as s:
        report = sweep_conversations(s, apply=False)
        assert report["stale_conversations"] >= 1 and old in threads_of(s, subject)
    # The beat's task runs the conversation sweep in anonymous mode too.
    result = worker.cleanup()
    assert "skipped" in result and result["stale_conversations"] >= 1
    with SessionLocal() as s:
        assert threads_of(s, subject) == [recent]


# ---------------------------------------------------------------------------------------------------
# Schema: Alembic owns the tables, pinned to the library's migrations
# ---------------------------------------------------------------------------------------------------


def test_alembic_carries_every_migration_of_the_pinned_library():
    import hashlib

    migrations = PostgresSaver.MIGRATIONS
    assert len(migrations) == checkpoint.MIGRATIONS_APPLIED, (
        "langgraph-checkpoint-postgres added a migration: copy it into a new Alembic revision and "
        "raise MIGRATIONS_APPLIED (openspec advisor-persistence D2)"
    )
    assert hashlib.sha256("\n--\n".join(migrations).encode()).hexdigest() == checkpoint.MIGRATIONS_DIGEST
    with SessionLocal() as s:
        assert s.scalar(text("SELECT max(v) FROM checkpoint_migrations")) == checkpoint.MIGRATIONS_APPLIED - 1
