from collections.abc import Callable, Mapping
import re
from typing import Any

from .build import NodeHandler, NodeObserver, build_advisor_graph
from .state import AdvisorState


_OPAQUE_REF = re.compile(r"^[0-9a-f]{64}$")


def _validate_checkpoint_payload(state: AdvisorState, configurable: dict[str, Any] | None) -> None:
    if state.profile_snapshot is not None or state.messages:
        raise ValueError("checkpoint input must not contain applicant profiles or raw messages")
    for ref in (state.user_id, state.thread_id):
        if ref and not _OPAQUE_REF.fullmatch(ref):
            raise ValueError("checkpoint identifiers must be opaque SHA-256 references")
    checkpoint_thread = (configurable or {}).get("thread_id")
    if not isinstance(checkpoint_thread, str) or not _OPAQUE_REF.fullmatch(checkpoint_thread):
        raise ValueError("checkpointer thread_id must be an opaque SHA-256 reference")


def run_advisor_turn(
    state: AdvisorState | dict[str, Any],
    *,
    handlers: Mapping[str, NodeHandler] | None = None,
    on_node: NodeObserver | None = None,
    checkpointer: Any = None,
    configurable: dict[str, Any] | None = None,
) -> AdvisorState:
    validated = state if isinstance(state, AdvisorState) else AdvisorState.model_validate(state)
    if checkpointer is not None:
        _validate_checkpoint_payload(validated, configurable)
    graph = build_advisor_graph(on_node=on_node, checkpointer=checkpointer, handlers=handlers)
    result = graph.invoke(validated.model_dump(), {"configurable": configurable or {}})
    return AdvisorState.model_validate(result)


async def arun_advisor_turn(
    state: AdvisorState | dict[str, Any],
    *,
    handlers: Mapping[str, NodeHandler] | None = None,
    on_node: NodeObserver | None = None,
    checkpointer: Any = None,
    configurable: dict[str, Any] | None = None,
) -> AdvisorState:
    validated = state if isinstance(state, AdvisorState) else AdvisorState.model_validate(state)
    if checkpointer is not None:
        _validate_checkpoint_payload(validated, configurable)
    graph = build_advisor_graph(on_node=on_node, checkpointer=checkpointer, handlers=handlers)
    result = await graph.ainvoke(validated.model_dump(), {"configurable": configurable or {}})
    return AdvisorState.model_validate(result)
