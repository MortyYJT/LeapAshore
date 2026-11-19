"""The advisor endpoints. Replies stream as server-sent events, one JSON object per event.

Event types: ``step`` (one thing the agent does, see below), ``intent`` (the router's decision),
``citations`` (the evidence the gate let through, or for a question answered from the official pages,
the passages its checked sentences cite), ``tool`` (a tool the agent called), ``token`` (a piece of the
reply), ``confirm`` (a portfolio change waiting for the applicant, with the ``id`` a confirm sends
back), ``error``, ``stopped`` (the turn ended because the applicant stopped it) and a final ``done``.

A ``step`` event describes the turn as the interface draws it, a line of stops:

- it opens a step with ``status: "running"``, an ``id`` that stays the same for the step's life, a
  ``kind`` (``intent``, ``retrieval`` or ``tool``), the ``name`` of the node or tool, a ``title`` in
  the applicant's words when one is known, and ``args``, the call's arguments as labelled values;
- it closes the step with the same ``id`` and a ``status`` of ``done``, ``empty`` (it ran and found
  nothing), ``failed``, ``waiting`` (it asked the applicant to confirm), ``declined`` or ``stopped``,
  with ``ms`` (how long it took) and ``result``, one line. ``write: true`` marks a step that wrote.

A change the applicant confirms is written in a step of its own, ``<call id>:write``, so the
transcript shows the proposal, the answer and the write. `app.agent.steps` decides the wording, and
what an event may carry: a tool's reply is never copied into one.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import limits
from app.agent import halt, steps
from app.agent.checkpoint import TurnLock, thread_id
from app.agent.graph import graph
from app.agent.llm import UNAVAILABLE, model_configured, outage
from app.agent.tools import wrote
from app.config import settings
from app.db import SessionLocal
from app.deps import get_subject, set_client_cookie, subject_cookie_header
from app.models.program import Program
from app.net import client_ip

router = APIRouter(prefix="/api/advisor", tags=["advisor"])
logger = logging.getLogger(__name__)

_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class ChatIn(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    message: str = Field(min_length=1, max_length=2000)


class StopIn(BaseModel):
    conversation_id: str = Field(alias="conversationId")


class ConfirmIn(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    approved: bool
    # The `id` of the `confirm` event being answered. When given, the answer applies to that change
    # only: a repeated click that arrives after the turn has moved on to a new change is not taken as
    # an answer to the new one. Optional, so a page loaded before this field existed still works.
    interrupt_id: str | None = Field(default=None, alias="interruptId", max_length=64)


async def _admit(request: Request, response: Response, subject: str, *, windows: bool) -> limits.Ticket:
    """Refuse with 429 over a limit, 503 when the limit store is down (openspec advisor-limits).

    Called from the endpoint bodies, after FastAPI has validated the request: a dependency would run
    before validation and take a window slot and a reservation for a request that is then a 422.
    """
    try:
        outcome = await limits.check(subject, client_ip(request), windows=windows)
    except limits.LimitsUnavailable:
        logger.exception("advisor limits unavailable; refusing the turn")
        raise HTTPException(
            503,
            {"code": "limits_unavailable", "message": limits.UNAVAILABLE},
            headers=subject_cookie_header(response),
        ) from None
    if isinstance(outcome, limits.Refusal):
        headers = {"Retry-After": str(outcome.retry_after), **(subject_cookie_header(response) or {})}
        raise HTTPException(429, outcome.detail(), headers=headers)
    return outcome


def _config(client_id: str, conversation_id: str, ticket: limits.Ticket | None = None) -> dict:
    if not _CONVERSATION_ID.match(conversation_id):
        raise HTTPException(422, "conversationId must be 1-40 letters, digits, '-' or '_'")
    # The thread is scoped by the cookie's client id, so one applicant cannot resume another's thread
    # by guessing a conversation id; tools read the same client id from here.
    config: dict = {"configurable": {"thread_id": thread_id(client_id, conversation_id), "client_id": client_id}}
    if ticket is not None:
        # Every model call in the turn is charged to the ticket's subject, IP and the site.
        config["callbacks"] = [limits.UsageRecorder(ticket.subject, ticket.ip)]
    return config


# Turns that are still running, so a turn whose client went away is not garbage-collected mid-run.
_turns: set[asyncio.Task] = set()


def _detached(
    events: AsyncIterator[str], ticket: limits.Ticket, after: Callable[[], Awaitable[None]] | None = None
) -> AsyncIterator[str]:
    """Start the turn now, in its own task, and return a generator that relays its events.

    The response generator is cancelled when the client disconnects; if the model calls ran inside it,
    a client that hung up before the last chunk (which carries the usage) would never be charged. In a
    task of its own the turn finishes, its usage is recorded, and the reservation is given back
    whatever the client does. The task starts here rather than on the first read, because a client
    that disconnects before the response starts streaming means the generator is never read at all,
    and its reservation would then stay on today's counters. A dropped client's events are not read.
    ``after`` runs once the turn has ended and been settled, whatever happened (pruning the thread,
    releasing a confirm's lock).
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def run() -> None:
        try:
            async for event in events:
                queue.put_nowait(event)
        finally:
            try:
                await limits.settle(ticket)
            finally:
                try:
                    if after is not None:
                        await after()
                finally:
                    queue.put_nowait(None)

    task = asyncio.create_task(run())
    _turns.add(task)
    task.add_done_callback(_turns.discard)

    async def relay() -> AsyncIterator[str]:
        while (event := await queue.get()) is not None:
            yield event

    return relay()


# The two errors a turn can end on (the `code` of the `error` event). The model's provider not answering
# is told apart from a fault of ours: the first passes, the second needs a fix.
FAILED = "顾问暂时出错了，请稍后再试。"
# Added when a tool had already written in the turn (a confirmed portfolio change, a profile update):
# what it wrote stands, and the applicant should not do it again.
SAVED_BEFORE_OUTAGE = "这一轮里已经执行的操作已保存。"


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _program_name(program_id: str) -> str | None:
    """A program's name for a step's arguments; the model only knows its id. Never raises."""
    try:
        with SessionLocal() as session:
            program = session.get(Program, program_id)
            return f"{program.university.name} {program.name}" if program else None
    except Exception:  # noqa: BLE001 - a step shows the id rather than break the turn
        logger.warning("could not name program %s for a step", program_id, exc_info=True)
        return None


@dataclass
class Resumed:
    """What a confirm resumes: the tool calls the paused step left unanswered, and the answer."""

    approved: bool
    # The unanswered calls of the paused step, as the model made them.
    calls: list[dict] = field(default_factory=list)
    # The call that asked the question, when it can be told apart.
    asked: str | None = None


def _paused_calls(snapshot, interrupt_id: str | None) -> tuple[list[dict], str | None]:
    """The tool calls a paused turn is waiting on, and the id of the one that asked the question."""
    messages = (snapshot.values or {}).get("messages", [])
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    calls = [c for c in (last.tool_calls if last else []) if c["id"] not in answered]
    values = [i.value for i in snapshot.interrupts if interrupt_id is None or i.id == interrupt_id]
    return calls, _asking_call(calls, values[0] if values else {})


def _asking_call(calls: list[dict], question) -> str | None:
    """Which of `calls` raised this confirm question: the one whose tool the question names, or the
    only call there is."""
    tool = question.get("tool") if isinstance(question, dict) else None
    named = [c["id"] for c in calls if c["name"] == tool]
    if named:
        return named[0]
    return calls[0]["id"] if len(calls) == 1 else None


class _Steps:
    """The steps of one stream: which are open, when each started, and their events."""

    def __init__(self) -> None:
        self._open: dict[str, tuple[float, str, str]] = {}  # id -> (started, kind, name)
        self.turn = uuid.uuid4().hex[:8]

    def own(self, part: str) -> str:
        """An id for a step that is not a tool call; unique in the conversation."""
        return f"{self.turn}-{part}"

    def start(self, step_id: str, kind: str, name: str, *, title: str | None = None, **fields) -> str:
        self._open[step_id] = (time.monotonic(), kind, name)
        payload = {"type": "step", "id": step_id, "status": steps.RUNNING, "kind": kind, "name": name,
                   "title": title or steps.title(name), **fields}
        return _event({k: v for k, v in payload.items() if v not in (None, [], False)})

    def resume(self, step_id: str, kind: str, name: str) -> str:
        """A step an earlier stream left waiting runs again; the interface already knows what it is."""
        self._open[step_id] = (time.monotonic(), kind, name)
        return _event({"type": "step", "id": step_id, "status": steps.RUNNING})

    def finish(self, step_id: str, status: str, result: str | None = None, **fields) -> str:
        opened = self._open.pop(step_id, None)
        payload: dict = {"type": "step", "id": step_id, "status": status}
        if opened is not None:
            payload["ms"] = round((time.monotonic() - opened[0]) * 1000)
        if result:
            payload["result"] = result
        payload.update({k: v for k, v in fields.items() if v not in (None, [], False)})
        return _event(payload)

    def end(self, step_id: str, outcome: steps.Outcome) -> str:
        return self.finish(step_id, outcome.status, **outcome.fields())

    def name_of(self, step_id: str) -> str | None:
        opened = self._open.get(step_id)
        return opened[2] if opened else None

    def open_tools(self) -> list[tuple[str, str]]:
        return [(step_id, name) for step_id, (_, kind, name) in self._open.items() if kind == steps.TOOL]

    def close_all(self, status: str, result: str) -> list[str]:
        return [self.finish(step_id, status, result) for step_id in list(self._open)]


async def _stream(graph_input, config: dict, resumed: Resumed | None = None) -> AsyncIterator[str]:
    if not model_configured():
        yield _event({"type": "error", "code": "not_configured", "message": "顾问模型尚未配置（缺少 CHAT_API_KEY）。"})
        yield _event({"type": "done"})
        return
    thread = config["configurable"]["thread_id"]
    run = _Steps()
    retrieval, check = run.own("retrieval"), run.own("check")
    wrote_something = False
    paused = False
    try:
        if resumed is None:
            yield run.start(run.own("intent"), steps.INTENT, "classify_intent")
        else:
            # The paused step runs again from its top (`interrupt` re-enters the tool), so every call
            # it left unanswered is answered in this stream.
            for call in resumed.calls:
                if call["id"] != resumed.asked:
                    yield run.resume(call["id"], steps.TOOL, call["name"])
                elif resumed.approved:
                    yield run.start(f"{call['id']}:write", steps.TOOL, call["name"], title=steps.WRITE_TITLE, write=True)
        # `durability="sync"`: each step's checkpoint is saved before the next step starts, so a process
        # that dies after a confirmed write leaves the thread past that write (openspec
        # advisor-persistence D4).
        async for mode, data in graph.astream(
            graph_input, config, stream_mode=["messages", "updates"], durability="sync"
        ):
            if mode == "messages":
                chunk, meta = data
                if (
                    meta.get("langgraph_node") == "main_agent"
                    and isinstance(chunk, AIMessageChunk)
                    and isinstance(chunk.content, str)
                    and chunk.content
                ):
                    yield _event({"type": "token", "text": chunk.content})
                continue
            for node, update in data.items():
                if node == "__interrupt__":
                    paused = True
                    waiting = run.open_tools()
                    for item in update:
                        question = item.value if isinstance(item.value, dict) else {"summary": str(item.value)}
                        asked = _asking_call([{"id": i, "name": n} for i, n in waiting], question)
                        if asked:
                            yield run.finish(asked, steps.WAITING, steps.WAITING_FOR_ANSWER)
                        # `type` last: the interrupt payload carries its own `type`, which must not
                        # replace the event type the client switches on.
                        tied = {"stepId": asked} if asked else {}
                        yield _event({**question, "kind": question.get("type"), "id": item.id, **tied, "type": "confirm"})
                    # A call made beside the one that asked has not answered either: the step is
                    # run again, whole, once the applicant has.
                    for step_id, _ in run.open_tools():
                        yield run.finish(step_id, steps.WAITING)
                elif node == "classify_intent":
                    route = (update.get("trace") or {}).get("route")
                    yield run.finish(run.own("intent"), steps.DONE, steps.intent_result(update["intent"], route))
                    yield _event(
                        {"type": "intent", "intent": update["intent"], "confidence": update["intent_confidence"]}
                    )
                    if route == "requirements":
                        yield run.start(retrieval, steps.RETRIEVAL, "retrieve_requirements")
                    elif route == "passages":
                        yield run.start(retrieval, steps.RETRIEVAL, "retrieve_passages")
                elif node == "retrieve_requirements":
                    yield run.end(retrieval, steps.requirements_result(update))
                    yield _event(
                        {
                            "type": "citations",
                            "gate": "pass" if update.get("evidence_strong") else "refuse",
                            "citations": update.get("citations", []),
                        }
                    )
                elif node == "retrieve_passages":
                    yield run.end(retrieval, steps.passages_result(update))
                    if update.get("evidence_strong"):
                        yield run.start(check, steps.RETRIEVAL, "answer_passages")
                    else:
                        yield _event({"type": "citations", "gate": "refuse", "citations": []})
                elif node == "answer_passages":
                    yield run.end(check, steps.check_result(update))
                    # Sent whole once every quote has been checked (openspec snapshot-rag D9).
                    yield _event({
                        "type": "citations",
                        "gate": "pass" if update.get("citations") else "refuse",
                        "citations": update.get("citations", []),
                    })
                    yield _event({"type": "token", "text": update["messages"][0].content})
                elif node == "refuse":
                    yield _event({"type": "token", "text": update["messages"][0].content})
                elif node == "tools":
                    for message in (update or {}).get("messages", []):
                        if not isinstance(message, ToolMessage):
                            continue
                        wrote_something = wrote_something or wrote(message)
                        call_id = message.tool_call_id
                        name = message.name or run.name_of(call_id) or run.name_of(f"{call_id}:write") or ""
                        outcome = steps.call_result(name, message)
                        if resumed is not None and call_id == resumed.asked:
                            if resumed.approved:
                                yield run.finish(call_id, steps.DONE, steps.CONFIRMED)
                                yield run.end(f"{call_id}:write", outcome)
                            else:
                                yield run.finish(call_id, outcome.status, outcome.result)
                        else:
                            yield run.end(call_id, outcome)
                elif node == "main_agent":
                    msg = update["messages"][-1]
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        for call in msg.tool_calls:
                            args = call.get("args") or {}
                            # The model names a program by its id; the applicant reads its name.
                            named = await asyncio.to_thread(_program_name, str(args["program_id"])) if args.get("program_id") else None
                            yield run.start(
                                call["id"], steps.TOOL, call["name"],
                                args=steps.call_args(call["name"], args, program_name=lambda _id, named=named: named),
                                write=call["name"] in steps.WRITES_DIRECTLY,
                            )
                            yield _event({"type": "tool", "name": call["name"]})
    except Exception as error:  # noqa: BLE001 - the stream must close with an error event, not hang
        for event in run.close_all(steps.FAILED, steps.INTERRUPTED):
            yield event
        if outage(error):
            # Expected while the provider is down (an account out of money answers every call with 402):
            # one line, no traceback per turn.
            logger.warning("advisor model unavailable: %s: %s", type(error).__name__, str(error)[:300])
            message = UNAVAILABLE + (SAVED_BEFORE_OUTAGE if wrote_something else "")
            yield _event({"type": "error", "code": "model_unavailable", "message": message})
        else:
            logger.exception("advisor stream failed")
            yield _event({"type": "error", "code": "advisor_failed", "message": FAILED})
    else:
        if halt.requested(thread):
            # Asked to stop: the graph ended at its next edge. A tool the model had asked for was not run.
            for event in run.close_all(steps.STOPPED, steps.HALTED):
                yield event
            yield _event({"type": "stopped", "wrote": wrote_something})
        elif not paused:
            # Only the step cap leaves a call open at a normal end (`graph.should_continue`).
            for event in run.close_all(steps.STOPPED, steps.OUT_OF_STEPS):
                yield event
    yield _event({"type": "done"})


def _sse(body: AsyncIterator[str], client_id: str) -> StreamingResponse:
    response = StreamingResponse(
        body, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
    # Without this the stream carries no cookie, every message becomes a new subject, and the thread
    # that holds the conversation (and any paused portfolio change) is never found again. In login
    # mode the subject comes from the session cookie, and no anonymous cookie is minted.
    if not settings.auth_enabled:
        set_client_cookie(response, client_id)
    return response


async def _nothing_to_confirm() -> AsyncIterator[str]:
    yield _event({"type": "error", "code": "nothing_pending", "message": "没有待确认的操作，可能已经处理过或已过期。"})
    yield _event({"type": "done"})


async def _already_confirming() -> AsyncIterator[str]:
    yield _event({"type": "error", "code": "confirm_in_progress", "message": "这个操作正在处理，请稍候。"})
    yield _event({"type": "done"})


def _pending(snapshot, interrupt_id: str | None) -> bool:
    """A change is waiting, and it is the one being answered when the answer names it."""
    if not snapshot.interrupts:
        return False
    return interrupt_id is None or any(i.id == interrupt_id for i in snapshot.interrupts)


def _tidy(config: dict) -> Callable[[], Awaitable[None]]:
    """After a turn: keep only the thread's latest checkpoint (D6). Best effort; a failure is logged."""
    thread = config["configurable"]["thread_id"]

    async def prune() -> None:
        try:
            await graph.checkpointer.aprune([thread], strategy="keep_latest")
        except Exception:  # noqa: BLE001 - a thread left unpruned costs space, not correctness
            logger.warning("could not prune advisor thread", exc_info=True)

    return prune


# Turns running in this process, by thread, each with the event that is set when it has ended. One
# thread runs one turn at a time: a second turn would start from a checkpoint the first is about to
# replace, and one of the two replies would be lost from the conversation.
_running: dict[str, asyncio.Event] = {}
# How long a new message waits for the turn before it to stop. The call in flight is not cancelled
# (`app.agent.halt`), so this is bounded by one model call.
TAKE_OVER_SECONDS = 20
BUSY = "上一轮还没停下来，请过几秒再发。"


def _claim(thread: str) -> asyncio.Event:
    """Mark the thread as running a turn; the turn sets the returned event when it ends."""
    ended = asyncio.Event()
    _running[thread] = ended
    return ended


async def _take_over(thread: str) -> asyncio.Event | None:
    """Claim the thread for a new message: ask a turn still running on it to stop and wait for it to
    end. Returns the new turn's event, or None when the thread was not free in time."""
    deadline = time.monotonic() + TAKE_OVER_SECONDS
    # Checked again after every wait: another message may have claimed the thread first.
    while (previous := _running.get(thread)) is not None:
        halt.request(thread)
        try:
            await asyncio.wait_for(previous.wait(), max(0.0, deadline - time.monotonic()))
        except TimeoutError:
            return None
    return _claim(thread)


def _release(thread: str, ended: asyncio.Event) -> None:
    """The turn has ended: a stop asked of it must not reach the next turn."""
    if _running.get(thread) is ended:
        del _running[thread]
        halt.clear(thread)
    ended.set()


async def _busy() -> AsyncIterator[str]:
    yield _event({"type": "error", "code": "busy", "message": BUSY})
    yield _event({"type": "done"})


@router.post("/chat")
async def chat(
    body: ChatIn, request: Request, response: Response, client_id: Annotated[str, Depends(get_subject)]
) -> StreamingResponse:
    thread = _config(client_id, body.conversation_id)["configurable"]["thread_id"]
    ended = await _take_over(thread)
    if ended is None:
        return _sse(_busy(), client_id)
    try:
        ticket = await _admit(request, response, client_id, windows=True)
    except BaseException:
        _release(thread, ended)
        raise
    config = _config(client_id, body.conversation_id, ticket)
    tidy = _tidy(config)

    async def after() -> None:
        try:
            await tidy()
        finally:
            _release(thread, ended)

    turn = _stream({"messages": [HumanMessage(content=body.message)], "trace": None}, config)
    return _sse(_detached(turn, ticket, after=after), client_id)


@router.post("/stop")
async def stop(body: StopIn, client_id: Annotated[str, Depends(get_subject)]) -> dict:
    """Ask the turn running in this conversation to stop.

    The node that is running finishes (a model call in flight is charged as usual) and nothing else
    starts: a tool the model was about to call is not run. A turn that has already ended, or one that
    is waiting for a confirm, has nothing to stop.
    """
    thread = _config(client_id, body.conversation_id)["configurable"]["thread_id"]
    running = thread in _running
    if running:
        halt.request(thread)
    return {"stopping": running}


@router.post("/confirm")
async def confirm(
    body: ConfirmIn, request: Request, response: Response, client_id: Annotated[str, Depends(get_subject)]
) -> StreamingResponse:
    """Resume a turn the agent paused on a portfolio change, with the applicant's answer.

    The change is written at most once however often, and from however many tabs, it is answered
    (openspec advisor-persistence D5): one confirm per thread holds the thread's lock while its turn
    runs, a confirm that finds the lock taken is told the change is being handled, and the paused state
    is read again under the lock, so a confirm that waited behind a finished one finds nothing to do.
    """
    config = _config(client_id, body.conversation_id)
    thread = config["configurable"]["thread_id"]
    # Resuming a thread that is not paused would start a fresh turn with no message in it.
    if not _pending(await graph.aget_state(config), body.interrupt_id):
        return _sse(_nothing_to_confirm(), client_id)
    lock = TurnLock(thread)
    if not await lock.acquire():
        return _sse(_already_confirming(), client_id)
    ended: asyncio.Event | None = None
    try:
        snapshot = await graph.aget_state(config)
        if not _pending(snapshot, body.interrupt_id):
            await lock.release()
            return _sse(_nothing_to_confirm(), client_id)
        # A message sent a moment ago may still be running on this thread; the answer is for the
        # change that is on screen, not for a turn that has moved on.
        if thread in _running:
            await lock.release()
            return _sse(_already_confirming(), client_id)
        ended = _claim(thread)
        # A confirm resumes a turn that already took a window slot, and runs only when a change is
        # pending, so it is held to the token caps only; refusing it on a window would strand the change
        # (D7).
        ticket = await _admit(request, response, client_id, windows=False)
    except BaseException:
        if ended is not None:
            _release(thread, ended)
        await lock.release()
        raise
    config = _config(client_id, body.conversation_id, ticket)
    tidy = _tidy(config)

    async def after() -> None:
        try:
            await tidy()
        finally:
            try:
                await lock.release()
            finally:
                _release(thread, ended)

    calls, asked = _paused_calls(snapshot, body.interrupt_id)
    # Named, the answer resumes exactly that change; unnamed (an older page), the only one pending.
    resume = {body.interrupt_id: body.approved} if body.interrupt_id else body.approved
    turn = _stream(Command(resume=resume), config, Resumed(approved=body.approved, calls=calls, asked=asked))
    return _sse(_detached(turn, ticket, after=after), client_id)


@router.get("/status")
def status() -> dict:
    return {"configured": model_configured()}
