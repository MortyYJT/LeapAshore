"""The advisor endpoints. Replies stream as server-sent events, one JSON object per event.

Event types: ``intent`` (the router's decision), ``citations`` (the evidence the gate let through),
``tool`` (a tool the agent called), ``token`` (a piece of the reply), ``confirm`` (a portfolio change
waiting for the applicant), ``error``, and a final ``done``.
"""

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.agent.graph import graph
from app.agent.llm import model_configured
from app.config import settings
from app.deps import get_subject, set_client_cookie

router = APIRouter(prefix="/api/advisor", tags=["advisor"])
logger = logging.getLogger(__name__)

_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class ChatIn(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    message: str = Field(min_length=1, max_length=2000)


class ConfirmIn(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    approved: bool


def _config(client_id: str, conversation_id: str) -> dict:
    if not _CONVERSATION_ID.match(conversation_id):
        raise HTTPException(422, "conversationId must be 1-40 letters, digits, '-' or '_'")
    # The thread is scoped by the cookie's client id, so one applicant cannot resume another's thread
    # by guessing a conversation id; tools read the same client id from here.
    return {"configurable": {"thread_id": f"{client_id}:{conversation_id}", "client_id": client_id}}


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream(graph_input, config: dict) -> AsyncIterator[str]:
    if not model_configured():
        yield _event({"type": "error", "message": "顾问模型尚未配置（缺少 CHAT_API_KEY）。"})
        yield _event({"type": "done"})
        return
    try:
        async for mode, data in graph.astream(graph_input, config, stream_mode=["messages", "updates"]):
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
                        yield _event({**item.value, "kind": item.value.get("type"), "type": "confirm"})
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


@router.post("/chat")
async def chat(body: ChatIn, client_id: Annotated[str, Depends(get_subject)]) -> StreamingResponse:
    config = _config(client_id, body.conversation_id)
    return _sse(_stream({"messages": [HumanMessage(content=body.message)], "trace": None}, config), client_id)


@router.post("/confirm")
async def confirm(body: ConfirmIn, client_id: Annotated[str, Depends(get_subject)]) -> StreamingResponse:
    """Resume a turn the agent paused on a portfolio change, with the applicant's answer."""
    config = _config(client_id, body.conversation_id)
    # Resuming a thread that is not paused would start a fresh turn with no message in it.
    snapshot = await graph.aget_state(config)
    if not snapshot.interrupts:
        return _sse(_nothing_to_confirm(), client_id)
    return _sse(_stream(Command(resume=body.approved), config), client_id)


@router.get("/status")
def status() -> dict:
    return {"configured": model_configured()}
