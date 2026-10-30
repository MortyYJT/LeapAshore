"""The advisor graph.

    START -> classify_intent -+-> retrieve_requirements -> evidence gate -+-> main_agent <-> tools -> END
                              |                                          +-> refuse -> END
                              +-> retrieve_passages -> passage gate -+-> answer_passages -> END
                              |                                      +-> refuse -> END
                              +-> main_agent <-> tools -> END

The router decides the exit from the intent, requirement questions take a
deterministic retrieval path whose gate runs *before* the model writes anything, and the ReAct loop
stops on a step count rather than a token budget, because a step is one model call and is easy to
count and explain.
"""

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent import answer, evidence, intent, passages
from app.agent.checkpoint import checkpointer
from app.agent.llm import get_chat_model
from app.agent.state import AdvisorState
from app.agent.tools import TOOLS
from app.config import settings
from app.db import SessionLocal

SYSTEM_PROMPT = """你是鱼跃彼岸的留学申请顾问，帮中国学生规划海外硕士申请。

铁律：
1. 不编造录取要求、截止日期、均分门槛或来源。只能引用下方"已检索证据"或工具返回的内容。
2. 引用证据时在句末标注编号，例如 [1]。证据标注"待核验"的，必须明确告诉用户"该数据待核验，请以官网为准"，并给出来源链接。证据里某一项后面写了（出处 …）的，引用这一项时给这个出处链接，不要给项目页链接；标了（已截止）的截止日期要说明已经过了。
3. 没有来源的问题直接说查不到，不要猜。不提供签证、移民等法律类建议。
4. 用户提供了新的背景信息时，用 update_my_profile 记下来（可以直接执行）。
5. 修改选校组合（加入、移出、设首选）只能用 propose_portfolio_change，它会请用户确认，不要说"已经帮你改好"直到工具返回已执行。
6. 回答简洁，用中文。"""

EVIDENCE_HINT = "\n\n## 已检索证据（只能据此回答官方要求，逐条标注编号）\n"

# Used only when a refusal arrives without its own text; the gate words every refusal from the
# catalogue's counts (`evidence.refusal`), so no school list is written here.
FALLBACK_REFUSAL = "这个问题涉及的学校或项目还没有收录官方数据，我不能凭印象回答，以免你照着错误的要求去申请。已记录为待采集。"


def _last_user_text(state: AdvisorState) -> str:
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            return m.content if isinstance(m.content, str) else ""
    return ""


def _history_text(state: AdvisorState, turns: int = 6) -> str:
    lines = []
    for m in state.get("messages", [])[:-1][-turns:]:
        if isinstance(m, (HumanMessage, AIMessage)) and isinstance(m.content, str) and m.content:
            lines.append(f"{'用户' if isinstance(m, HumanMessage) else '顾问'}：{m.content}")
    return "\n".join(lines)


async def classify_intent(state: AdvisorState) -> dict:
    question = _last_user_text(state)
    result = await intent.classify(question, _history_text(state))
    with SessionLocal() as session:
        # A question about tuition, references or an interview that names a school is answered from the
        # official pages, whose words can be checked; the catalogue's columns do not hold these
        # (openspec snapshot-rag D6).
        topics = passages.route(session, question, result["intent"])
    route = "passages" if topics else intent.INTENT_TO_ROUTE.get(result["intent"], "agent")
    return {
        "intent": result["intent"],
        "intent_confidence": result["confidence"],
        # Each turn starts clean: last turn's evidence must not leak into this one.
        "evidence": "",
        "citations": [],
        "passages": [],
        "page_topics": [t.key for t in topics],
        "steps": 0,
        "trace": {"intent": result["intent"], "confidence": result["confidence"], "route": route},
    }


def route_by_intent(state: AdvisorState) -> str:
    if state.get("page_topics"):
        return "passages"
    return intent.INTENT_TO_ROUTE.get(state.get("intent", ""), "agent")


def retrieve_passages(state: AdvisorState) -> dict:
    wanted = set(state.get("page_topics") or [])
    topics = [t for t in passages.detect_topics(_last_user_text(state)) if t.key in wanted]
    with SessionLocal() as session:
        return passages.gate(session, _last_user_text(state), topics)


async def answer_passages(state: AdvisorState) -> dict:
    """Answer from the passages, then keep only the sentences whose quotes check out (D8, D9). The reply
    is sent whole, after the check: an unchecked sentence is never streamed."""
    found = state.get("passages") or []
    model = get_chat_model(temperature=0)
    reply = await answer.generate(_last_user_text(state), found, model=model)
    checked = answer.verify(reply.answer, [p["text"] for p in found])
    # Whether each quote backs its sentence: one more call, only when a sentence is left to show.
    support = await answer.support_check(_last_user_text(state), checked, found, model)
    if not checked.kept:
        text, citations = answer.refusal_after_check(found), []
    else:
        text, citations = answer.render(checked, found)
    return {
        "messages": [AIMessage(content=text)],
        "citations": citations,
        "trace": {"citation_check": checked.summary(), "answered": bool(checked.kept),
                  **({"answer_error": reply.error} if reply.error else {}),
                  **({"support_error": support.error} if support.error else {})},
    }


def retrieve_requirements(state: AdvisorState) -> dict:
    with SessionLocal() as session:
        return evidence.gate(session, _last_user_text(state))


def evidence_gate(state: AdvisorState) -> str:
    return "strong" if state.get("evidence_strong") else "weak"


def refuse(state: AdvisorState) -> dict:
    return {"messages": [AIMessage(content=state.get("refusal_text") or FALLBACK_REFUSAL)]}


# What the model is told about a tool call that never got an answer (see `with_unanswered_calls_closed`).
UNANSWERED_CALL = "未执行：用户没有回应这个操作，接着发了新消息。"


def with_unanswered_calls_closed(messages: list[AnyMessage]) -> list[AnyMessage]:
    """The history with a tool reply after every tool call that has none, for the model's eyes only.

    A turn paused on a confirm leaves the model's tool call unanswered; when the applicant writes again
    instead of answering, the new turn starts over and the call stays unanswered in the thread. An
    OpenAI-style API refuses a history like that, and with conversations kept in Postgres the thread
    would stay unusable after any restart (openspec advisor-persistence D8). The stored thread is not
    changed.
    """
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    out: list[AnyMessage] = []
    for m in messages:
        out.append(m)
        if isinstance(m, AIMessage):
            for call in m.tool_calls:
                if call["id"] not in answered:
                    out.append(ToolMessage(content=UNANSWERED_CALL, tool_call_id=call["id"]))
    return out


CONFIRMED_TOOL = "propose_portfolio_change"


def one_change_per_step(reply: AIMessage) -> AIMessage:
    """Keep only the first portfolio change of a reply that asks for several at once.

    Every `interrupt` in one step shares the step's id, and a step that pauses twice hands the first
    answer to whichever of its parallel tool calls asks first. One change per step gives each confirm
    card its own id and its own answer (openspec advisor-persistence D5). The dropped calls never reach
    the history, so the model sees the first change's outcome and proposes the next one itself.
    """
    calls = [c for c in reply.tool_calls if c["name"] == CONFIRMED_TOOL]
    if len(calls) < 2:
        return reply
    dropped = {c["id"] for c in calls[1:]}
    # The raw OpenAI calls would otherwise be sent back alongside the kept ones.
    extra = {k: v for k, v in reply.additional_kwargs.items() if k != "tool_calls"}
    return reply.model_copy(
        update={"tool_calls": [c for c in reply.tool_calls if c["id"] not in dropped], "additional_kwargs": extra}
    )


async def main_agent(state: AdvisorState) -> dict:
    system = SYSTEM_PROMPT
    if state.get("evidence"):
        system += EVIDENCE_HINT + state["evidence"]
    model = get_chat_model(streaming=True).bind_tools(TOOLS)
    history = with_unanswered_calls_closed(state["messages"])
    reply = one_change_per_step(await model.ainvoke([SystemMessage(content=system), *history]))
    return {"messages": [reply], "steps": state.get("steps", 0) + 1}


def should_continue(state: AdvisorState) -> str:
    """Stop when the model calls no tool, or when the step cap is reached."""
    last = state["messages"][-1]
    if not (isinstance(last, AIMessage) and last.tool_calls):
        return "stop"
    if state.get("steps", 0) >= settings.max_agent_steps:
        return "stop"
    return "continue"


def build_graph(checkpointer=None):
    b = StateGraph(AdvisorState)
    b.add_node("classify_intent", classify_intent)
    b.add_node("retrieve_requirements", retrieve_requirements)
    b.add_node("refuse", refuse)
    b.add_node("retrieve_passages", retrieve_passages)
    b.add_node("answer_passages", answer_passages)
    b.add_node("main_agent", main_agent)
    b.add_node("tools", ToolNode(TOOLS))

    b.add_edge(START, "classify_intent")
    b.add_conditional_edges(
        "classify_intent", route_by_intent,
        {"requirements": "retrieve_requirements", "passages": "retrieve_passages", "agent": "main_agent"},
    )
    b.add_conditional_edges(
        "retrieve_passages", evidence_gate, {"strong": "answer_passages", "weak": "refuse"}
    )
    b.add_edge("answer_passages", END)
    b.add_conditional_edges(
        "retrieve_requirements", evidence_gate, {"strong": "main_agent", "weak": "refuse"}
    )
    b.add_conditional_edges("main_agent", should_continue, {"continue": "tools", "stop": END})
    b.add_edge("tools", "main_agent")
    b.add_edge("refuse", END)
    return b.compile(checkpointer=checkpointer)


# Conversations live in Postgres (openspec advisor-persistence): a turn paused on a confirm survives a
# restart of the API, and every process that builds this graph sees the same threads.
graph = build_graph(checkpointer=checkpointer)
