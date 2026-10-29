"""Unit tests for the advisor graph's deterministic parts: routing, the step cap and the source check.

None of these call a model or the database.
"""

from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.agent import evidence, intent
from app.agent.graph import build_graph, route_by_intent, should_continue
from app.agent.state import merge_dict
from app.config import settings


def _tool_call_message() -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "get_my_profile", "args": {}, "id": "c1"}])


def test_requirement_questions_take_the_retrieval_path_and_everything_else_the_agent():
    assert route_by_intent({"intent": "官方要求核验"}) == "requirements"
    for name in ("规划", "资料补充", "业务操作", "通用问答"):
        assert route_by_intent({"intent": name}) == "agent"


def test_an_unknown_intent_goes_to_the_agent():
    assert route_by_intent({"intent": "不存在"}) == "agent"
    assert route_by_intent({}) == "agent"


def test_every_intent_has_a_route():
    assert set(intent.INTENTS) == set(intent.INTENT_TO_ROUTE)
    assert intent.FALLBACK_INTENT in intent.INTENTS


def test_the_loop_stops_when_the_model_calls_no_tool():
    assert should_continue({"messages": [AIMessage(content="好的")], "steps": 1}) == "stop"


def test_the_loop_continues_on_a_tool_call_below_the_cap():
    assert should_continue({"messages": [_tool_call_message()], "steps": 1}) == "continue"


def test_the_step_cap_stops_a_tool_loop():
    state = {"messages": [_tool_call_message()], "steps": settings.max_agent_steps}
    assert should_continue(state) == "stop"


def test_none_resets_the_trace_and_a_dict_merges_into_it():
    assert merge_dict({"a": 1}, None) == {}
    assert merge_dict({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3}


def test_only_an_https_source_with_a_title_and_an_id_is_citable():
    ok = SimpleNamespace(id="s1", title="UNSW MIT", url="https://www.unsw.edu.au/x")
    assert evidence._citable(ok)
    assert not evidence._citable(None)
    assert not evidence._citable(SimpleNamespace(id="s1", title="UNSW MIT", url="http://www.unsw.edu.au/x"))
    assert not evidence._citable(SimpleNamespace(id="s1", title="", url="https://www.unsw.edu.au/x"))


def test_an_unknown_mark_is_written_as_unknown_not_zero():
    assert evidence._fmt_mark(None) == "未知"
    assert evidence._fmt_mark(65) == "65"


def test_a_subject_alone_is_refused_as_no_school(monkeypatch):
    """Asking about an uncollected school must not borrow another school's requirements: a subject
    with no school named returns no rows and is refused."""
    found = evidence.Retrieval(schools=[], fields=["计算机与数据"], hits=[])
    monkeypatch.setattr(evidence, "search_requirements", lambda session, query: found)
    monkeypatch.setattr(evidence, "_catalogue_counts", lambda session: (2, 10, ["甲大学", "乙大学"]))
    update = evidence.gate(session=None, query="MIT 的计算机硕士要什么条件？")
    assert update["evidence_strong"] is False
    assert update["refusal"] == "no_school"
    assert "2 所学校" in update["refusal_text"] and "甲大学" in update["refusal_text"]


def test_the_graph_compiles_with_every_node_wired():
    nodes = set(build_graph().get_graph().nodes)
    assert {"classify_intent", "retrieve_requirements", "refuse", "main_agent", "tools"} <= nodes


def test_the_advisor_stream_sets_the_client_cookie(monkeypatch):
    """A streamed reply must carry the subject cookie, or every message starts a new subject."""
    from fastapi.testclient import TestClient

    from app.agent import llm
    from app.main import app

    monkeypatch.setattr(llm.settings, "chat_api_key", "")
    response = TestClient(app).post("/api/advisor/chat", json={"conversationId": "t1", "message": "hi"})
    assert response.status_code == 200
    assert "leapashore_client=" in response.headers.get("set-cookie", "")
