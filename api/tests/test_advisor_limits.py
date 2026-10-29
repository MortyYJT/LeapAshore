"""Advisor rate limits and token quotas (openspec/changes/advisor-limits).

These run against the development Redis (`compose.yaml`, port 56379; CI runs a service), each test
under its own key prefix (`isolate_the_advisor_limits` in conftest). The model is never called: the
stream is replaced, or the key is left empty so the advisor answers that it is not configured.
"""

import asyncio
import types
import uuid

import pytest
import redis
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app import limits
from app.config import settings
from app.main import app
from app.routers import advisor
from tests.auth_helpers import login, login_mode, new_client, outbox, unique_ip  # noqa: F401 - fixtures

CHAT = "/api/advisor/chat"
CONFIRM = "/api/advisor/confirm"


def ask(client: TestClient, ip: str | None = None, conversation: str = "c1"):
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post(CHAT, json={"conversationId": conversation, "message": "你好"}, headers=headers)


@pytest.fixture
def quiet_stream(monkeypatch):
    """Replace the graph run with an empty stream, recording the config each turn was given."""
    seen: list[dict] = []

    async def fake_stream(graph_input, config):
        seen.append(config)
        yield advisor._event({"type": "done"})

    monkeypatch.setattr(advisor, "_stream", fake_stream)
    return seen


@pytest.fixture
def behind_caddy(monkeypatch):
    """The TestClient's peer is `testclient`; listing it makes it the trusted proxy."""
    monkeypatch.setattr(settings, "trusted_proxies", "testclient")


@pytest.fixture
def generous(monkeypatch):
    """Limits nobody reaches, so a test tightens only the one it is about."""
    monkeypatch.setattr(settings, "advisor_subject_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_daily_tokens_per_subject", 10**9)
    monkeypatch.setattr(settings, "advisor_daily_tokens_per_ip", 10**9)
    monkeypatch.setattr(settings, "advisor_daily_tokens_site", 10**9)


def sync_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


# ---------- configuration ----------


def test_window_specs_parse_and_bad_ones_are_refused():
    assert limits.parse_windows("10/60, 60/3600") == [(10, 60), (60, 3600)]
    assert limits.parse_windows("") == []
    for bad in ("10", "10/0", "a/60", "10/60/3", "-1/60"):
        with pytest.raises(ValueError):
            limits.parse_windows(bad)


# ---------- windows ----------


def test_a_subject_is_refused_after_its_window_fills(quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_subject_limits", "2/60")
    client = TestClient(app)
    assert ask(client).status_code == 200
    assert ask(client).status_code == 200
    refused = ask(client)
    assert refused.status_code == 429
    detail = refused.json()["detail"]
    assert detail["code"] == "rate_limited"
    assert "太频繁" in detail["message"]
    assert 0 < detail["retryAfter"] <= 60
    assert refused.headers["retry-after"] == str(detail["retryAfter"])
    # The refused turn never reached the graph.
    assert len(quiet_stream) == 2


def test_a_new_anonymous_cookie_does_not_escape_the_ip_window(quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_ip_limits", "2/60")
    assert ask(TestClient(app)).status_code == 200
    assert ask(TestClient(app)).status_code == 200
    assert ask(TestClient(app)).status_code == 429


def test_switching_account_is_still_blocked_by_the_same_ip(
    login_mode, behind_caddy, quiet_stream, generous, monkeypatch
):
    monkeypatch.setattr(settings, "advisor_ip_limits", "2/60")
    ip = unique_ip()
    a, b = new_client(), new_client()
    login(a, login_mode)
    login(b, login_mode)
    assert ask(a, ip).status_code == 200
    assert ask(a, ip).status_code == 200
    refused = ask(b, ip)
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "rate_limited"
    # The same account from another address is let through: it was the IP that was full.
    assert ask(b, unique_ip()).status_code == 200


def test_a_forged_forwarding_header_has_no_effect(quiet_stream, generous, monkeypatch):
    # The peer is not a listed proxy, so X-Forwarded-For is the client's own claim.
    monkeypatch.setattr(settings, "trusted_proxies", "")
    monkeypatch.setattr(settings, "advisor_ip_limits", "2/60")
    assert ask(TestClient(app), unique_ip()).status_code == 200
    assert ask(TestClient(app), unique_ip()).status_code == 200
    # A fresh cookie and a fresh claimed address: still the same peer, still refused.
    assert ask(TestClient(app), unique_ip()).status_code == 429


def test_a_refused_request_does_not_take_a_slot(quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_subject_limits", "1/60")
    client = TestClient(app)
    assert ask(client).status_code == 200
    for _ in range(3):
        assert ask(client).status_code == 429
    keys = list(sync_redis().scan_iter(match=settings.limits_key_prefix + "win:subject:*"))
    assert len(keys) == 1
    assert sync_redis().zcard(keys[0]) == 1


def test_the_window_slides(quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_subject_limits", "1/1")
    client = TestClient(app)
    assert ask(client).status_code == 200
    assert ask(client).status_code == 429
    asyncio.run(asyncio.sleep(1.05))
    assert ask(client).status_code == 200


def test_a_logged_out_request_is_refused_before_it_takes_a_slot(login_mode, quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_ip_limits", "1/60")
    assert new_client().post(CHAT, json={"conversationId": "c1", "message": "你好"}).status_code == 401
    assert ask(TestClient(app)).status_code == 401
    client = new_client()
    login(client, login_mode)
    assert ask(client).status_code == 200


def test_confirm_is_not_windowed(quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_subject_limits", "1/60")
    client = TestClient(app)
    assert ask(client).status_code == 200
    assert ask(client).status_code == 429
    # Nothing is pending, so the confirm answers without a model call, but it is not refused.
    answered = client.post(CONFIRM, json={"conversationId": "c1", "approved": True})
    assert answered.status_code == 200


# ---------- token caps ----------


def subject_of(client: TestClient) -> str:
    return client.cookies.get("leapashore_client")


def test_a_subject_over_its_daily_tokens_is_refused(quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_daily_tokens_per_subject", 100)
    client = TestClient(app)
    assert ask(client).status_code == 200
    asyncio.run(limits.record_usage(subject_of(client), "198.51.100.1", 100))
    refused = ask(client)
    assert refused.status_code == 429
    detail = refused.json()["detail"]
    assert detail["code"] == "daily_tokens_subject"
    assert "额度" in detail["message"]
    assert 0 < detail["retryAfter"] <= 24 * 3600
    # A confirm with a change pending resumes the model, so the cap applies to it.
    pending = types.SimpleNamespace(interrupts=["pending change"])

    async def paused(config):
        return pending

    monkeypatch.setattr(advisor.graph, "aget_state", paused)
    assert client.post(CONFIRM, json={"conversationId": "c1", "approved": True}).status_code == 429
    # Someone else is unaffected.
    assert ask(TestClient(app)).status_code == 200


def test_an_ip_over_its_daily_tokens_is_refused(behind_caddy, quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_daily_tokens_per_ip", 100)
    ip = unique_ip()
    asyncio.run(limits.record_usage(str(uuid.uuid4()), ip, 100))
    refused = ask(TestClient(app), ip)
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "daily_tokens_ip"
    assert ask(TestClient(app), unique_ip()).status_code == 200


def test_the_site_cap_refuses_everyone(behind_caddy, quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_daily_tokens_site", 50)
    asyncio.run(limits.record_usage(str(uuid.uuid4()), unique_ip(), 50))
    refused = ask(TestClient(app), unique_ip())
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "daily_tokens_site"
    assert "全站" in refused.json()["detail"]["message"]


def test_the_default_site_cap_is_two_million():
    from app.config import Settings

    assert Settings(_env_file=None).advisor_daily_tokens_site == 2_000_000


def test_usage_is_counted_from_the_model_report(generous):
    subject, ip = str(uuid.uuid4()), unique_ip()
    recorder = limits.UsageRecorder(subject, ip)
    message = AIMessage(content="好", usage_metadata={"input_tokens": 90, "output_tokens": 33, "total_tokens": 123})
    asyncio.run(recorder.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=uuid.uuid4()))
    # A provider that reports only the OpenAI `token_usage` block is counted too.
    bare = LLMResult(
        generations=[[ChatGeneration(message=AIMessage(content="x"))]],
        llm_output={"token_usage": {"total_tokens": 7}},
    )
    asyncio.run(recorder.on_llm_end(bare, run_id=uuid.uuid4()))
    used = asyncio.run(limits.usage_today(subject, ip))
    assert used == {"subject": 130, "ip": 130, "site": 130}


USAGE = {"input_tokens": 40, "output_tokens": 2, "total_tokens": 42}


@pytest.fixture
def streaming_model(monkeypatch):
    """A model that streams like ChatOpenAI with `stream_usage`: text chunks, then a usage chunk.

    The graph runs for real around it (intent fixed to general Q&A), so the test sees whether the
    recorder rides the graph config into the model call inside the agent node.
    """
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk, ChatResult

    from app.agent import graph as graph_module
    from app.agent import intent, llm

    class Streaming(BaseChatModel):
        delay: float = 0.0

        @property
        def _llm_type(self) -> str:
            return "fake-streaming"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="好的", usage_metadata=USAGE))])

        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            for text in ("好", "的"):
                await asyncio.sleep(self.delay)
                chunk = ChatGenerationChunk(message=AIMessageChunk(content=text))
                if run_manager:
                    await run_manager.on_llm_new_token(text, chunk=chunk)
                yield chunk
            await asyncio.sleep(self.delay)
            yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=USAGE))

    model = Streaming()

    async def fixed_intent(query, history):
        return {"intent": "通用问答", "confidence": 1.0}

    monkeypatch.setattr(llm.settings, "chat_api_key", "test-key")
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: model)
    monkeypatch.setattr(intent, "classify", fixed_intent)
    return model


def test_a_turn_charges_the_tokens_its_model_calls_report(generous, streaming_model):
    client = TestClient(app)
    response = ask(client, conversation=f"t{uuid.uuid4().hex[:8]}")
    assert response.status_code == 200
    assert '"type": "token"' in response.text
    used = asyncio.run(limits.usage_today(subject_of(client), "testclient"))
    # The reservation has been given back: what is left is what the model reported.
    assert used == {"subject": 42, "ip": 42, "site": 42}


def test_a_client_that_hangs_up_is_still_charged(generous, streaming_model, monkeypatch):
    """The usage arrives in the last chunk; a client gone before it must not make the turn free."""
    from langchain_core.messages import HumanMessage

    monkeypatch.setattr(settings, "advisor_turn_token_reserve", 1000)
    streaming_model.delay = 0.05
    subject, ip = str(uuid.uuid4()), unique_ip()

    async def hang_up_after_the_first_event() -> None:
        ticket = await limits.check(subject, ip)
        config = advisor._config(subject, "c1", ticket)
        body = advisor._detached(advisor._stream({"messages": [HumanMessage(content="你好")], "trace": None}, config), ticket)
        await body.__anext__()
        await body.aclose()
        assert (await limits.usage_today(subject, ip))["subject"] >= 1000
        await asyncio.gather(*advisor._turns)

    asyncio.run(hang_up_after_the_first_event())
    assert asyncio.run(limits.usage_today(subject, ip)) == {"subject": 42, "ip": 42, "site": 42}


def test_a_response_that_never_streams_still_returns_its_reservation(generous, monkeypatch):
    """A client gone before the first byte: the relay is never read, the reservation must still go back."""
    monkeypatch.setattr(settings, "advisor_turn_token_reserve", 1000)
    subject, ip = str(uuid.uuid4()), unique_ip()

    async def empty_turn():
        yield advisor._event({"type": "done"})

    async def admitted_but_never_read() -> None:
        ticket = await limits.check(subject, ip)
        advisor._detached(empty_turn(), ticket)
        await asyncio.gather(*advisor._turns)

    asyncio.run(admitted_but_never_read())
    assert asyncio.run(limits.usage_today(subject, ip)) == {"subject": 0, "ip": 0, "site": 0}


def test_a_running_turn_holds_its_reservation(generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_turn_token_reserve", 1000)
    during = []

    async def fake_stream(graph_input, config):
        recorder = config["callbacks"][0]
        during.append(await limits.usage_today(recorder.subject, recorder.ip))
        yield advisor._event({"type": "done"})

    monkeypatch.setattr(advisor, "_stream", fake_stream)
    client = TestClient(app)
    assert ask(client).status_code == 200
    assert during == [{"subject": 1000, "ip": 1000, "site": 1000}]
    assert asyncio.run(limits.usage_today(subject_of(client), "testclient")) == {"subject": 0, "ip": 0, "site": 0}


def test_turns_admitted_together_count_each_other_s_reservation(generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_turn_token_reserve", 1000)
    monkeypatch.setattr(settings, "advisor_daily_tokens_site", 2000)

    async def three_at_once():
        return await asyncio.gather(*(limits.check(str(uuid.uuid4()), unique_ip()) for _ in range(3)))

    outcomes = asyncio.run(three_at_once())
    assert sum(isinstance(o, limits.Ticket) for o in outcomes) == 2
    assert [o.code for o in outcomes if isinstance(o, limits.Refusal)] == ["daily_tokens_site"]


def test_an_invalid_request_takes_no_slot(quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_subject_limits", "1/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1/60")
    client = TestClient(app)
    assert client.post(CHAT, json={"conversationId": "c1", "message": ""}).status_code == 422
    assert client.post(CHAT, json={"conversationId": "bad id!", "message": "你好"}).status_code == 422
    assert ask(client).status_code == 200
    assert ask(client).status_code == 429


# ---------- the store is down ----------


def test_the_advisor_fails_closed_without_redis(quiet_stream, generous, monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    response = ask(TestClient(app))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "limits_unavailable"
    assert "暂时不可用" in response.json()["detail"]["message"]
    assert quiet_stream == []
    # The rest of the site does not touch Redis.
    assert TestClient(app).get("/api/advisor/status").status_code == 200


class _LateReplies:
    """The real client, except that chosen scripts run in Redis and then their reply times out.

    `late` maps a script to how many of its calls lose their reply; `held` scripts are not sent at
    all: their arguments are kept, the call times out, and the test runs them later (a command still
    in flight when the caller gave up).
    """

    def __init__(self, real, late=None, held=()):
        self.real, self.late, self.held, self.kept = real, dict(late or {}), set(held), []

    async def eval(self, script, *args):
        if script in self.held:
            self.held.discard(script)
            self.kept.append((script, args))
            raise redis.exceptions.TimeoutError("Timeout reading from socket")
        reply = await self.real.eval(script, *args)
        if self.late.get(script, 0) > 0:
            self.late[script] -= 1
            raise redis.exceptions.TimeoutError("Timeout reading from socket")
        return reply

    def __getattr__(self, name):
        return getattr(self.real, name)


def test_an_admission_whose_reply_timed_out_gives_its_reservation_back(quiet_stream, generous, monkeypatch):
    """The script ran (slot taken, tokens reserved) but the reply was lost: the 503 must undo both."""
    monkeypatch.setattr(settings, "advisor_turn_token_reserve", 8000)
    monkeypatch.setattr(settings, "advisor_subject_limits", "1/60")
    real_client = limits._client
    monkeypatch.setattr(limits, "_client", lambda: _LateReplies(real_client(), late={limits._CHECK: 1}))
    client = TestClient(app)
    response = ask(client)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "limits_unavailable"
    assert quiet_stream == []
    subject = subject_of(client)
    assert asyncio.run(limits.usage_today(subject, "testclient")) == {"subject": 0, "ip": 0, "site": 0}
    # The lost admission did not keep its window slot either.
    monkeypatch.setattr(limits, "_client", real_client)
    assert ask(client).status_code == 200


def test_an_admission_that_lands_after_its_withdrawal_reserves_nothing(generous, monkeypatch):
    """The caller gave up before Redis ran the script; when it does run, it must not reserve."""
    monkeypatch.setattr(settings, "advisor_turn_token_reserve", 8000)
    subject, ip = str(uuid.uuid4()), unique_ip()
    real_client = limits._client

    async def scenario():
        late = _LateReplies(real_client(), held={limits._CHECK})
        monkeypatch.setattr(limits, "_client", lambda: late)
        with pytest.raises(limits.LimitsUnavailable):
            await limits.check(subject, ip)
        await asyncio.gather(*limits._withdrawals)
        (script, args), = late.kept
        index, _ = await real_client().eval(script, *args)
        assert int(index) != 0
        return await limits.usage_today(subject, ip)

    assert asyncio.run(scenario()) == {"subject": 0, "ip": 0, "site": 0}


def test_a_withdrawal_retried_after_its_own_lost_reply_refunds_once(generous, monkeypatch):
    monkeypatch.setattr(settings, "advisor_turn_token_reserve", 8000)
    monkeypatch.setattr(limits, "WITHDRAW_RETRY_DELAYS", (0, 0))
    subject, ip = str(uuid.uuid4()), unique_ip()
    real_client = limits._client

    async def scenario():
        late = _LateReplies(real_client(), late={limits._CHECK: 1, limits._WITHDRAW: 2})
        monkeypatch.setattr(limits, "_client", lambda: late)
        with pytest.raises(limits.LimitsUnavailable):
            await limits.check(subject, ip)
        await asyncio.gather(*limits._withdrawals)
        return await limits.usage_today(subject, ip)

    assert asyncio.run(scenario()) == {"subject": 0, "ip": 0, "site": 0}


# ---------- model output limit ----------


def test_every_model_call_carries_max_tokens(monkeypatch):
    """DeepSeek ignores `max_completion_tokens`, which is what LangChain's own field is sent as."""
    from app.agent import llm

    monkeypatch.setattr(llm.settings, "chat_api_key", "test-key")
    monkeypatch.setattr(llm.settings, "chat_max_tokens", 1500)
    payload = llm.get_chat_model()._get_request_payload("hi")
    assert payload["extra_body"]["max_tokens"] == 1500
    assert "max_completion_tokens" not in payload
    assert llm.get_chat_model(max_tokens=200)._get_request_payload("hi")["extra_body"]["max_tokens"] == 200


def test_the_intent_router_has_its_own_small_limit(monkeypatch):
    from app.agent import intent

    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr(intent, "get_chat_model", spy)
    asyncio.run(intent.classify("你好", ""))
    assert captured["max_tokens"] == settings.intent_max_tokens
