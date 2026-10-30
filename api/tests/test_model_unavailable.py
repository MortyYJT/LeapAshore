"""What happens when the chat model's provider refuses every call (TASKS.md, 2026-10-30: the DeepSeek
account ran out of money and every call came back HTTP 402).

The applicant is told plainly that the advisor is unavailable, in Chinese: no 500, no refusal worded as
if the catalogue lacked the answer, no answer from a fallback route. The turn's token reservation goes
back. The collection queue puts the page back for a later day instead of failing it or recording an
empty result, and stops asking the model for a while.

The provider is a real `ChatOpenAI` over a mock transport answering with DeepSeek's recorded 402 body
(`tests/model_outage.py`), or that exception raised directly; no test reaches the network.
"""

import asyncio
import json
import uuid

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app import limits
from app.agent import answer, intent, llm
from app.agent import graph as graph_module
from app.agent.answer import CitedSentence, PassageAnswer, Quote
from app.config import settings
from app.main import app
from app.routers import advisor
from tests.model_outage import out_of_balance_model, status_error
from tests.test_snapshot_rag import Answering, school  # noqa: F401 - fixture

CHAT = "/api/advisor/chat"


def events(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def said(evts: list[dict]) -> str:
    return "".join(e.get("text", "") for e in evts if e["type"] == "token")


@pytest.fixture
def generous(monkeypatch):
    monkeypatch.setattr(settings, "advisor_subject_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_turn_token_reserve", 1000)
    monkeypatch.setattr(settings, "chat_api_key", "test-key")


# ---- telling an outage from other errors -----------------------------------------------------------------


@pytest.mark.parametrize(("status", "kind"), [
    (402, llm.ACCOUNT), (401, llm.ACCOUNT), (403, llm.ACCOUNT),
    (429, llm.TRANSIENT), (500, llm.TRANSIENT), (503, llm.TRANSIENT),
])
def test_provider_answers_are_sorted_into_account_and_transient_outages(status, kind):
    assert llm.outage(status_error(status)) == kind


def test_a_connection_failure_is_transient_and_a_bad_request_is_no_outage():
    request = httpx.Request("POST", "https://api.deepseek.test/chat/completions")
    assert llm.outage(openai.APIConnectionError(request=request)) == llm.TRANSIENT
    assert llm.outage(openai.APITimeoutError(request=request)) == llm.TRANSIENT
    assert llm.outage(status_error(400, {"error": {"message": "bad"}})) is None
    assert llm.outage(ValueError("parse")) is None


def test_an_outage_wrapped_in_another_error_is_still_found():
    try:
        try:
            raise status_error(402)
        except openai.APIStatusError as error:
            raise RuntimeError("node failed") from error
    except RuntimeError as wrapped:
        assert llm.outage(wrapped) == llm.ACCOUNT


# ---- the advisor -----------------------------------------------------------------------------------------


def test_an_out_of_balance_model_tells_the_applicant_and_gives_the_reservation_back(generous, monkeypatch):
    calls: list = []
    monkeypatch.setattr(intent, "get_chat_model", lambda **kw: out_of_balance_model(calls))
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kw: out_of_balance_model(calls))
    client = TestClient(app)
    response = client.post(CHAT, json={"conversationId": f"o{uuid.uuid4().hex[:8]}", "message": "墨尔本大学数据科学硕士雅思要求？"})
    assert response.status_code == 200
    evts = events(response)
    errors = [e for e in evts if e["type"] == "error"]
    assert errors == [{"type": "error", "code": "model_unavailable", "message": llm.UNAVAILABLE}]
    assert evts[-1] == {"type": "done"}
    # The router does not fall back to another route that calls the model again: one request, no answer.
    assert len(calls) == 1 and said(evts) == ""
    subject = next(iter(client.cookies.values()))
    assert asyncio.run(limits.usage_today(subject, "testclient")) == {"subject": 0, "ip": 0, "site": 0}


def test_an_outage_in_the_agent_after_the_router_is_the_same_message(generous, monkeypatch):
    async def general(query, history):
        return {"intent": "通用问答", "confidence": 1.0}

    monkeypatch.setattr(intent, "classify", general)
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kw: out_of_balance_model())
    response = TestClient(app).post(CHAT, json={"conversationId": f"o{uuid.uuid4().hex[:8]}", "message": "你好"})
    assert [e["message"] for e in events(response) if e["type"] == "error"] == [llm.UNAVAILABLE]


def test_another_failure_keeps_the_generic_message(generous, monkeypatch):
    async def general(query, history):
        return {"intent": "通用问答", "confidence": 1.0}

    class Broken(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "broken"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise ValueError("a bug, not an outage")

    monkeypatch.setattr(intent, "classify", general)
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kw: Broken())
    response = TestClient(app).post(CHAT, json={"conversationId": f"o{uuid.uuid4().hex[:8]}", "message": "你好"})
    errors = [e for e in events(response) if e["type"] == "error"]
    assert errors == [{"type": "error", "code": "advisor_failed", "message": advisor.FAILED}]


def test_the_router_still_falls_back_on_an_unreadable_answer(monkeypatch):
    class Garbled(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "garbled"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="not a function call"))])

    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(intent, "get_chat_model", lambda **kw: Garbled())
    assert asyncio.run(intent.classify("你好", "")) == {"intent": intent.FALLBACK_INTENT, "confidence": 0.0}


def test_a_router_outage_is_raised_not_hidden(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(intent, "get_chat_model", lambda **kw: out_of_balance_model())
    with pytest.raises(openai.APIStatusError):
        asyncio.run(intent.classify("你好", ""))


# ---- the answer from official pages ---------------------------------------------------------------------


def test_a_judge_outage_is_raised_not_turned_into_a_refusal():
    verification = answer.verify(
        PassageAnswer(sentences=[CitedSentence(text="学费每年 61,000 美元。", citations=[
            Quote(passage=1, quote="Tuition fee: US$61,000 per year.")])]),
        ["Tuition fee: US$61,000 per year."],
    )
    assert verification.kept
    passages = [{"url": "https://x.example/p", "school": "X", "program": "MDS", "text": "Tuition fee: US$61,000 per year."}]
    with pytest.raises(openai.APIStatusError):
        asyncio.run(answer.support_check("学费？", verification, passages, out_of_balance_model()))


class JudgeOutOfMoney(Answering):
    """Answers the passage question, then the provider refuses the judge's call."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.tool == "Verdicts":
            raise status_error(402)
        return super()._generate(messages, stop, run_manager, **kwargs)


def test_a_turn_whose_judge_hits_an_outage_says_unavailable_not_refused(school, generous, monkeypatch):  # noqa: F811
    async def requirement(query, history):
        return {"intent": "官方要求核验", "confidence": 0.9}

    args = {"sentences": [{"text": "数据科学硕士学费每年 61,000 美元。",
                           "citations": [{"passage": 1, "quote": "Tuition fee: US$61,000 per year."}]}]}
    monkeypatch.setattr(intent, "classify", requirement)
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kw: JudgeOutOfMoney(arguments=args))
    response = TestClient(app).post(CHAT, json={"conversationId": f"o{uuid.uuid4().hex[:8]}",
                                                "message": "切片检索测试大学数据科学硕士学费多少？"})
    evts = events(response)
    assert [e["message"] for e in evts if e["type"] == "error"] == [llm.UNAVAILABLE]
    # Neither the unchecked sentence nor the "could not check" refusal is shown.
    assert "61,000" not in said(evts) and "不作判断" not in said(evts)


def test_a_turn_whose_answer_hits_an_outage_says_unavailable(school, generous, monkeypatch):  # noqa: F811
    async def requirement(query, history):
        return {"intent": "官方要求核验", "confidence": 0.9}

    monkeypatch.setattr(intent, "classify", requirement)
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kw: out_of_balance_model())
    response = TestClient(app).post(CHAT, json={"conversationId": f"o{uuid.uuid4().hex[:8]}",
                                                "message": "切片检索测试大学数据科学硕士学费多少？"})
    evts = events(response)
    assert [e["message"] for e in evts if e["type"] == "error"] == [llm.UNAVAILABLE]
    assert "不作判断" not in said(evts)
