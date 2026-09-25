from collections.abc import Callable, Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph

from .routing import classify_intent, route_intent
from .state import AdvisorState

NodeObserver = Callable[[str], None]
NodeHandler = Callable[[AdvisorState], dict[str, Any]]


def build_advisor_graph(
    *,
    on_node: NodeObserver | None = None,
    checkpointer: Any = None,
    handlers: Mapping[str, NodeHandler] | None = None,
):
    """Build the deterministic workflow; product services are injected by runtime adapters."""

    def observed(name: str, updates: dict[str, Any]):
        def run(state: AdvisorState) -> dict[str, Any]:
            if on_node:
                on_node(name)
            if handlers and name in handlers:
                return handlers[name](state)
            return updates(state) if callable(updates) else updates
        return run

    def classify(state: AdvisorState) -> dict[str, Any]:
        if on_node:
            on_node("classify")
        if handlers and "classify" in handlers:
            return handlers["classify"](state)
        message = next((m.get("content", "") for m in reversed(state.messages) if m.get("role") == "user"), "")
        return {"intent": classify_intent(str(message))}

    def decide(state: AdvisorState) -> dict[str, Any]:
        if on_node:
            on_node("route")
        if handlers and "route" in handlers:
            return handlers["route"](state)
        return {"route": route_intent(state.intent, ambiguous=False, profile_snapshot=state.profile_snapshot)}

    def response(name: str, content: str):
        def run(state: AdvisorState) -> dict[str, Any]:
            if on_node:
                on_node(name)
            if handlers and name in handlers:
                return handlers[name](state)
            return {"final_reply": content}
        return run

    def evidence_gate(state: AdvisorState) -> dict[str, Any]:
        if on_node:
            on_node("evidence_gate")
        if state.route == "retrieve_official_facts" and not state.knowledge_evidence:
            return {"final_reply": "我目前没有可核验的官方来源，暂时不能确认这个要求。"}
        if handlers and "evidence_gate" in handlers:
            return handlers["evidence_gate"](state)
        return {}

    def compose(state: AdvisorState) -> dict[str, Any]:
        if on_node:
            on_node("compose_reply")
        if handlers and "compose_reply" in handlers:
            return handlers["compose_reply"](state)
        return {"final_reply": state.final_reply or "我可以继续帮你梳理。"}

    graph = StateGraph(AdvisorState)
    graph.add_node("load_snapshot", observed("load_snapshot", {}))
    graph.add_node("resolve_context", observed("resolve_context", {}))
    graph.add_node("classify", classify)
    graph.add_node("route", decide)
    graph.add_node("clarify", response("clarify", "请再补充一些信息，我再继续帮你。"))
    graph.add_node("deterministic_action", response("deterministic_action", "我已整理好建议操作；需要你确认后才能执行。"))
    graph.add_node("retrieve_official_facts", response("retrieve_official_facts", ""))
    graph.add_node("deterministic_recommendation", response("deterministic_recommendation", "我会按已核验的确定性规则整理申请建议。"))
    graph.add_node("general_response", response("general_response", "你好，我可以帮你规划申请、核对官方要求或完善资料。"))
    graph.add_node("evidence_gate", evidence_gate)
    graph.add_node("compose_reply", compose)
    graph.add_edge(START, "load_snapshot")
    graph.add_edge("load_snapshot", "resolve_context")
    graph.add_edge("resolve_context", "classify")
    graph.add_edge("classify", "route")
    graph.add_conditional_edges("route", lambda state: state.route)
    for branch in ("clarify", "deterministic_action", "retrieve_official_facts", "deterministic_recommendation", "general_response"):
        graph.add_edge(branch, "evidence_gate")
    graph.add_edge("evidence_gate", "compose_reply")
    graph.add_edge("compose_reply", END)
    return graph.compile(checkpointer=checkpointer)
