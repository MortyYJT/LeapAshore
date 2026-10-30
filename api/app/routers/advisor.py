"""The advisor endpoints. Replies stream as server-sent events, one JSON object per event.

Event types: ``intent`` (the router's decision), ``citations`` (the evidence the gate let through, or
for a question answered from the official pages, the passages its checked sentences cite),
``tool`` (a tool the agent called), ``token`` (a piece of the reply), ``confirm`` (a portfolio change
waiting for the applicant, with the ``id`` a confirm sends back), ``error``, and a final ``done``.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import limits
from app.agent.checkpoint import TurnLock, thread_id
from app.agent.graph import graph
from app.agent.llm import model_configured
from app.config import settings
from app.deps import get_subject, set_client_cookie, subject_cookie_header
from app.net import client_ip

router = APIRouter(prefix="/api/advisor", tags=["advisor"])
logger = logging.getLogger(__name__)

_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class ChatIn(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    message: str = Field(min_length=1, max_length=2000)


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


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream(graph_input, config: dict) -> AsyncIterator[str]:
    if not model_configured():
        yield _event({"type": "error", "message": "顾问模型尚未配置（缺少 CHAT_API_KEY）。"})
        yield _event({"type": "done"})
        return
    try:
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
                    for item in update:
                        # `type` last: the interrupt payload carries its own `type`, which must not
                        # replace the event type the client switches on.
                        yield _event(
                            {**item.value, "kind": item.value.get("type"), "id": item.id, "type": "confirm"}
                        )
                elif node == "classify_intent":
                    yield _event(
                        {"type": "intent", "intent": update["intent"], "confidence": update["intent_confidence"]}
                    )
                elif node == "retrieve_requirements":
                    yield _event(
                        {
                            "type": "citations",
                            "gate": "pass" if update.get("evidence_strong") else "refuse",
                            "citations": update.get("citations", []),
                        }
                    )
                elif node == "retrieve_passages" and not update.get("evidence_strong"):
                    yield _event({"type": "citations", "gate": "refuse", "citations": []})
                elif node == "answer_passages":
                    # Sent whole once every quote has been checked (openspec snapshot-rag D9).
                    yield _event({
                        "type": "citations",
                        "gate": "pass" if update.get("citations") else "refuse",
                        "citations": update.get("citations", []),
                    })
                    yield _event({"type": "token", "text": update["messages"][0].content})
                elif node == "refuse":
                    yield _event({"type": "token", "text": update["messages"][0].content})
                elif node == "main_agent":
                    msg = update["messages"][-1]
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        for call in msg.tool_calls:
                            yield _event({"type": "tool", "name": call["name"]})
    except Exception:  # noqa: BLE001 - the stream must close with an error event, not hang
        logger.exception("advisor stream failed")
        yield _event({"type": "error", "message": "顾问暂时出错了，请稍后再试。"})
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
    yield _event({"type": "error", "message": "没有待确认的操作，可能已经处理过或已过期。"})
    yield _event({"type": "done"})


async def _already_confirming() -> AsyncIterator[str]:
    yield _event({"type": "error", "message": "这个操作正在处理，请稍候。"})
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


@router.post("/chat")
async def chat(
    body: ChatIn, request: Request, response: Response, client_id: Annotated[str, Depends(get_subject)]
) -> StreamingResponse:
    _config(client_id, body.conversation_id)
    ticket = await _admit(request, response, client_id, windows=True)
    config = _config(client_id, body.conversation_id, ticket)
    turn = _stream({"messages": [HumanMessage(content=body.message)], "trace": None}, config)
    return _sse(_detached(turn, ticket, after=_tidy(config)), client_id)


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
    # Resuming a thread that is not paused would start a fresh turn with no message in it.
    if not _pending(await graph.aget_state(config), body.interrupt_id):
        return _sse(_nothing_to_confirm(), client_id)
    lock = TurnLock(config["configurable"]["thread_id"])
    if not await lock.acquire():
        return _sse(_already_confirming(), client_id)
    try:
        if not _pending(await graph.aget_state(config), body.interrupt_id):
            await lock.release()
            return _sse(_nothing_to_confirm(), client_id)
        # A confirm resumes a turn that already took a window slot, and runs only when a change is
        # pending, so it is held to the token caps only; refusing it on a window would strand the change
        # (D7).
        ticket = await _admit(request, response, client_id, windows=False)
    except BaseException:
        await lock.release()
        raise
    config = _config(client_id, body.conversation_id, ticket)
    tidy = _tidy(config)

    async def after() -> None:
        try:
            await tidy()
        finally:
            await lock.release()

    # Named, the answer resumes exactly that change; unnamed (an older page), the only one pending.
    resume = {body.interrupt_id: body.approved} if body.interrupt_id else body.approved
    turn = _stream(Command(resume=resume), config)
    return _sse(_detached(turn, ticket, after=after), client_id)


@router.get("/status")
def status() -> dict:
    return {"configured": model_configured()}
