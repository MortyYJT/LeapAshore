"""The advisor graph.

    START -> classify_intent -+-> retrieve_requirements -> evidence gate -+-> main_agent <-> tools -> END
                              |                                          +-> refuse -> END
                              +-> main_agent <-> tools -> END

Ported from MEWHELP's graph: the router decides the exit from the intent, requirement questions take a
deterministic retrieval path whose gate runs *before* the model writes anything, and the ReAct loop
stops on a step count rather than a token budget, because a step is one model call and is easy to
count and explain.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent import evidence, intent
from app.agent.llm import get_chat_model
from app.agent.state import AdvisorState
from app.agent.tools import TOOLS
from app.config import settings
from app.db import SessionLocal

SYSTEM_PROMPT = """你是鱼跃彼岸的留学申请顾问，帮中国学生规划海外硕士申请。

铁律：
1. 不编造录取要求、截止日期、均分门槛或来源。只能引用下方"已检索证据"或工具返回的内容。
2. 引用证据时在句末标注编号，例如 [1]。证据标注"待核验"的，必须明确告诉用户"该数据待核验，请以官网为准"，并给出来源链接。
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
    result = await intent.classify(_last_user_text(state), _history_text(state))
    route = intent.INTENT_TO_ROUTE.get(result["intent"], "agent")
    return {
        "intent": result["intent"],
        "intent_confidence": result["confidence"],
        # Each turn starts clean: last turn's evidence must not leak into this one.
        "evidence": "",
        "citations": [],
        "steps": 0,
        "trace": {"intent": result["intent"], "confidence": result["confidence"], "route": route},
    }


def route_by_intent(state: AdvisorState) -> str:
    return intent.INTENT_TO_ROUTE.get(state.get("intent", ""), "agent")


def retrieve_requirements(state: AdvisorState) -> dict:
    with SessionLocal() as session:
        return evidence.gate(session, _last_user_text(state))


def evidence_gate(state: AdvisorState) -> str:
    return "strong" if state.get("evidence_strong") else "weak"


def refuse(state: AdvisorState) -> dict:
    return {"messages": [AIMessage(content=state.get("refusal_text") or FALLBACK_REFUSAL)]}


async def main_agent(state: AdvisorState) -> dict:
    system = SYSTEM_PROMPT
    if state.get("evidence"):
        system += EVIDENCE_HINT + state["evidence"]
    model = get_chat_model(streaming=True).bind_tools(TOOLS)
    reply = await model.ainvoke([SystemMessage(content=system), *state["messages"]])
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
    b.add_node("main_agent", main_agent)
    b.add_node("tools", ToolNode(TOOLS))

    b.add_edge(START, "classify_intent")
    b.add_conditional_edges(
        "classify_intent", route_by_intent, {"requirements": "retrieve_requirements", "agent": "main_agent"}
    )
    b.add_conditional_edges(
        "retrieve_requirements", evidence_gate, {"strong": "main_agent", "weak": "refuse"}
    )
    b.add_conditional_edges("main_agent", should_continue, {"continue": "tools", "stop": END})
    b.add_edge("tools", "main_agent")
    b.add_edge("refuse", END)
    return b.compile(checkpointer=checkpointer)


# One process, one in-memory checkpointer: conversations survive across requests but not a restart.
# Moving to a Postgres checkpointer is a schema change and waits for its own migration.
graph = build_graph(checkpointer=InMemorySaver())
