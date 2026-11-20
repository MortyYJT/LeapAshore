"""An applicant's own model key (docs/product/PRD-multi-device.md, 3.5).

The key arrives in a request header, is used in memory for that request, and is stored nowhere. These
tests run real turns through the endpoints against a stub of the provider that listens on a local
port, with a key that is easy to recognise, and then look for that key in every place a turn writes:
the log, every table of the database (the checkpoint tables' blobs included), both Redis databases, and
the stream sent back. The stub echoes the key in its error bodies, the worst a provider could do.
"""

import asyncio
import copy
import json
import logging
import pickle
import threading
from collections.abc import Iterator
from contextlib import contextmanager
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import limits
from app.agent import answer, checkpoint, embeddings, halt, llm, model_key
from app.agent import graph as graph_module
from app.agent.graph import build_graph
from app.config import settings
from app.db import SessionLocal, engine
from app.main import app
from app.models.program import Program
from app.routers import advisor
from app.seed import seed_programs
from app.seed_catalog import seed_catalog

pytestmark = pytest.mark.usefixtures("require_db")

CHAT, CONFIRM, CHECK = "/api/advisor/chat", "/api/advisor/confirm", "/api/advisor/key/check"
KEY = "sk-applicant-RECOGNISABLE-0123456789abcdef"
OTHER_KEY = "sk-applicant-SECOND-fedcba9876543210"
OWNER_KEY = "owner-chat-key"
OWNER_EMBED_KEY = "owner-embed-key"
# A phrase in the applicant's message. It is stored with the conversation, so finding it proves the
# searches below reach where a turn writes.
CANARY = "金丝雀暗号ZXQ"


def own(key: str = KEY, provider: str = "deepseek") -> dict[str, str]:
    return {model_key.KEY_HEADER: key, model_key.PROVIDER_HEADER: provider}


# ---------- a stub of the provider ----------


class Upstream:
    """An OpenAI-protocol server on a local port. It records the bearer key of every request."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []  # (path, bearer key)
        self.fail: int | str | None = None  # an HTTP status, or "hang"
        self.intent = "业务操作"
        self.propose: str | None = None  # a program id: the agent proposes adding it, then confirms
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # the stub's own access log is not the server's
                pass

            def _key(self) -> str:
                return (self.headers.get("Authorization") or "").removeprefix("Bearer ")

            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _refuse(self) -> bool:
                if upstream.fail == "hang":
                    time.sleep(1.5)
                    return False
                if isinstance(upstream.fail, int):
                    # Echo the whole key, as a careless provider might.
                    self._json(upstream.fail, {"error": {
                        "message": f"request refused for api key {self._key()} (Authorization: Bearer {self._key()})",
                        "type": "stub_error", "code": "stub"}})
                    return True
                return False

            def do_GET(self) -> None:
                upstream.seen.append((self.path, self._key()))
                if self._refuse():
                    return
                self._json(200, {"object": "list", "data": [{"id": "stub-model", "object": "model"}]})

            def do_POST(self) -> None:
                request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                upstream.seen.append((self.path, self._key()))
                if self.path.endswith("/embeddings"):
                    inputs = request["input"] if isinstance(request["input"], list) else [request["input"]]
                    self._json(200, {"data": [{"index": i, "embedding": [0.01] * 1024} for i in range(len(inputs))],
                                     "model": request.get("model"), "usage": {"total_tokens": 3}})
                    return
                if self._refuse():
                    return
                message = upstream.reply(request)
                usage = {"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35}
                finish = "tool_calls" if message.get("tool_calls") else "stop"
                if not request.get("stream"):
                    self._json(200, {"id": "stub", "object": "chat.completion", "model": "stub-model", "usage": usage,
                                     "choices": [{"index": 0, "message": message, "finish_reason": finish}]})
                    return
                delta = dict(message)
                if delta.get("tool_calls"):
                    delta["tool_calls"] = [{**c, "index": i} for i, c in enumerate(delta["tool_calls"])]
                chunks = [
                    {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                    {"choices": [], "usage": usage},
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in chunks:
                    payload = {"id": "stub", "object": "chat.completion.chunk", "model": "stub-model", **chunk}
                    self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reply(self, request: dict) -> dict:
        """The assistant message for one chat request."""
        tools = [t["function"]["name"] for t in request.get("tools") or []]
        if tools == ["IntentResult"]:
            arguments = json.dumps({"intent": self.intent, "confidence": 0.9}, ensure_ascii=False)
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-intent", "type": "function", "function": {"name": "IntentResult", "arguments": arguments}}]}
        answered = any(m.get("role") == "tool" for m in request["messages"])
        if self.propose and not answered:
            arguments = json.dumps({"program_id": self.propose, "action": "add", "tier": "稳"}, ensure_ascii=False)
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-propose", "type": "function",
                 "function": {"name": "propose_portfolio_change", "arguments": arguments}}]}
        return {"role": "assistant", "content": "好的。"}

    def keys(self, path_end: str = "/chat/completions") -> set[str]:
        return {key for path, key in self.seen if path.endswith(path_end)}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def upstream(monkeypatch):
    """The advisor on a checkpointer of its own, with the owner's key and both listed providers
    pointed at the stub."""
    stub = Upstream()
    # This laptop routes HTTP through a proxy; the stub is local.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    saver = checkpoint.Checkpointer()
    monkeypatch.setattr(advisor, "graph", build_graph(checkpointer=saver))
    monkeypatch.setattr(settings, "chat_api_key", OWNER_KEY)
    monkeypatch.setattr(settings, "chat_base_url", stub.url)
    monkeypatch.setattr(settings, "chat_timeout_seconds", 0.4)
    monkeypatch.setattr(settings, "embed_api_key", "")
    monkeypatch.setattr(settings, "advisor_subject_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1000/60")
    for provider in list(model_key.PROVIDERS.values()):
        monkeypatch.setitem(model_key.PROVIDERS, provider.id, replace(provider, base_url=stub.url))
    yield stub
    stub.close()
    saver.close()
    advisor._running.clear()
    halt._requested.clear()


@pytest.fixture
def program() -> Program:
    with SessionLocal() as s:
        seed_programs(s)
        seed_catalog(s)
        row = s.scalars(select(Program).order_by(Program.id).limit(1)).one()
        s.expunge_all()
        return row


@contextmanager
def browser() -> Iterator[TestClient]:
    """One client that keeps its cookie between requests. The client is not entered as a context
    manager: that would run the application's shutdown, which closes the checkpoint pool the other
    test files share."""
    yield TestClient(app)


def events(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def codes(evts: list[dict]) -> list[str]:
    return [e.get("code") for e in evts if e["type"] == "error"]


# ---------- where a turn could leave the key ----------


def transaction_mark() -> int:
    """The id of a new transaction: rows written from now on carry this id or a later one."""
    with engine.connect() as conn:
        return int(conn.execute(text("select txid_current() % 4294967296")).scalar())


def tables_holding(needle: str, since: int) -> list[str]:
    """The tables with a row written since `since` that holds `needle`, as text or inside a bytea
    column (which prints as hex). Every table of the schema is searched."""
    hexed = needle.encode().hex()
    found = []
    with engine.connect() as conn:
        for table in conn.execute(text("select tablename from pg_tables where schemaname = 'public'")).scalars():
            count = conn.execute(
                text(f'select count(*) from (select * from "{table}" where xmin::text::bigint >= :since offset 0) row '
                     "where row::text like :plain or row::text like :hexed"),
                {"since": since, "plain": f"%{needle}%", "hexed": f"%{hexed}%"},
            ).scalar()
            if count:
                found.append(table)
    return sorted(found)


def redis_holding(needle: str) -> list[str]:
    """The keys of the limits database and of Celery's broker database whose name or value holds `needle`."""
    found = []
    for url in (settings.redis_url, settings.celery_broker_url):
        client = redis.Redis.from_url(url, decode_responses=True)
        for key in client.scan_iter(count=1000):
            kind = client.type(key)
            if kind == "string":
                value = client.get(key)
            elif kind == "hash":
                value = client.hgetall(key)
            elif kind == "list":
                value = client.lrange(key, 0, -1)
            elif kind == "set":
                value = client.smembers(key)
            elif kind == "zset":
                value = client.zrange(key, 0, -1, withscores=True)
            else:
                value = client.dump(key)
            if needle in key or needle in repr(value):
                found.append(key)
        client.close()
    return found


def logged(caplog) -> str:
    """Everything the log captured, formatted as a handler would write it, with tracebacks."""
    formatter = logging.Formatter("%(name)s %(levelname)s %(message)s")
    return "\n".join(formatter.format(record) for record in caplog.records)


@pytest.fixture
def everything_logged(caplog):
    """Capture every logger at DEBUG, the HTTP client's and the OpenAI SDK's included."""
    caplog.set_level(logging.DEBUG)
    for name in ("httpx", "httpcore", "openai", "langchain", "langgraph", "app"):
        caplog.set_level(logging.DEBUG, logger=name)
    return caplog


def assert_key_left_nowhere(key: str, response, caplog, since: int) -> None:
    assert key not in response.text, "the stream"
    assert key not in json.dumps(dict(response.headers)), "the response headers"
    assert key not in logged(caplog), "the log"
    assert tables_holding(key, since) == [], "the database"
    assert redis_holding(key) == [], "redis"


# ---------- the provider list and the header ----------


def test_the_provider_list_is_fixed_and_names_each_endpoint_and_model():
    listed = {p.id: (p.base_url, p.model) for p in model_key.PROVIDERS.values()}
    assert listed == {
        "deepseek": ("https://api.deepseek.com", "deepseek-flash"),
        "siliconflow": ("https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V4-Flash"),
    }
    # DeepSeek thinks unless told not to, and refuses a named tool choice while thinking.
    assert model_key.PROVIDERS["deepseek"].extra_body == {"thinking": {"type": "disabled"}}


def test_no_header_means_the_owners_key():
    assert model_key.from_headers({}) is None
    assert model_key.from_headers({"x-model-provider": "deepseek"}) is None


@pytest.mark.parametrize("headers, code", [
    ({"x-model-key": KEY}, "model_provider_unknown"),
    ({"x-model-key": KEY, "x-model-provider": "openai"}, "model_provider_unknown"),
    ({"x-model-key": KEY, "x-model-provider": "https://evil.example/v1"}, "model_provider_unknown"),
    ({"x-model-key": "short", "x-model-provider": "deepseek"}, "model_key_malformed"),
    ({"x-model-key": KEY + " with spaces", "x-model-provider": "deepseek"}, "model_key_malformed"),
    ({"x-model-key": "k" * 300, "x-model-provider": "deepseek"}, "model_key_malformed"),
])
def test_a_bad_header_is_refused_without_repeating_it(headers, code):
    with pytest.raises(model_key.Refused) as refused:
        model_key.from_headers(headers)
    assert refused.value.code == code
    for value in headers.values():
        assert value not in refused.value.message and value not in repr(refused.value)


def test_a_key_has_no_printable_or_storable_form():
    key = model_key.from_headers(own())
    assert key.provider.id == "deepseek" and key.reveal() == KEY
    for shown in (repr(key), str(key), f"{key}", f"{key!r}", repr({"key": key}), repr(vars(key) if hasattr(key, "__dict__") else key)):
        assert KEY not in shown
    for store in (pickle.dumps, copy.copy, copy.deepcopy, json.dumps):
        with pytest.raises(TypeError):
            store(key)


def test_the_chat_model_takes_the_applicants_key_only_while_it_is_in_use(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", OWNER_KEY)
    monkeypatch.setattr(settings, "chat_base_url", "https://owner.example/v1")
    key = model_key.from_headers(own())
    with model_key.in_use(key):
        model = llm.get_chat_model(max_tokens=200)
        assert model.openai_api_key.get_secret_value() == KEY
        assert (model.openai_api_base, model.model_name) == ("https://api.deepseek.com", "deepseek-flash")
        assert model.extra_body == {"max_tokens": 200, "thinking": {"type": "disabled"}}
        assert KEY not in repr(model)
    after = llm.get_chat_model()
    assert after.openai_api_key.get_secret_value() == OWNER_KEY
    assert after.openai_api_base == "https://owner.example/v1"
    assert after.extra_body == {"max_tokens": settings.chat_max_tokens}


def test_the_applicants_key_works_when_the_owner_has_none(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "")
    with pytest.raises(llm.ModelNotConfigured):
        llm.get_chat_model()
    with model_key.in_use(model_key.from_headers(own())):
        assert llm.get_chat_model().openai_api_key.get_secret_value() == KEY


def test_text_is_scrubbed_of_a_key_only_while_it_is_in_use():
    key = model_key.from_headers(own())
    line = f"Authorization: Bearer {KEY}"
    assert model_key.scrub(line) == line
    with model_key.in_use(key):
        assert KEY not in model_key.scrub(line)
        assert model_key.scrub("nothing here") == "nothing here"
    assert model_key.scrub(line) == line


def test_a_log_record_made_while_a_key_is_in_use_never_holds_it(caplog):
    caplog.set_level(logging.DEBUG)
    log = logging.getLogger("some.library")
    with model_key.in_use(model_key.from_headers(own())):
        log.warning("refused: %s", f"Bearer {KEY}")
        log.info("headers %r", {"authorization": KEY})
        try:
            raise RuntimeError(f"<Request POST headers={{'authorization': 'Bearer {KEY}'}}>")
        except RuntimeError:
            log.exception("call failed")
    assert len(caplog.records) == 3
    assert KEY not in logged(caplog)
    for record in caplog.records:
        assert KEY not in repr(record.__dict__)
    assert "call failed" in logged(caplog) and "RuntimeError" in logged(caplog)


def test_a_judge_error_kept_with_the_turn_is_scrubbed():
    class Echoing:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, *args, **kwargs):
            raise ValueError(f"bad request for key {KEY}")

    page = "Tuition fees: A$53,000 per year for international students."
    reply = answer.PassageAnswer(sentences=[answer.CitedSentence(
        text="学费每年 53,000 澳元。", citations=[answer.Quote(passage=1, quote="Tuition fees: A$53,000 per year")])])
    checked = answer.verify(reply, [page])
    assert checked.kept, "the sentence passes the quote check, so the judge is asked"
    passages = [{"text": page, "title": "Fees", "url": "https://example.edu/fees"}]

    async def judged():
        with model_key.in_use(model_key.from_headers(own())):
            return await answer.support_check("学费多少", checked, passages, Echoing())

    judgement = asyncio.run(judged())
    assert judgement.error and "ValueError" in judgement.error
    assert KEY not in judgement.error


# ---------- a turn on the applicant's key ----------


def test_a_turn_uses_the_applicants_key_and_leaves_it_nowhere(upstream, everything_logged):
    since = transaction_mark()
    with browser() as client:
        response = client.post(CHAT, json={"conversationId": "k1", "message": f"你好 {CANARY}"}, headers=own())
    assert response.status_code == 200
    evts = events(response)
    assert codes(evts) == []
    assert any(e["type"] == "token" and "好的" in e["text"] for e in evts)
    # The stream says whose key the turn ran on, by provider.
    assert evts[0] == {"type": "model", "ownKey": True, "provider": "deepseek", "label": "DeepSeek"}
    assert upstream.keys() == {KEY}
    assert len(upstream.seen) >= 2  # the intent call and the reply
    assert_key_left_nowhere(KEY, response, everything_logged, since)
    # The same searches do find what a turn stores and logs.
    assert "checkpoint_blobs" in tables_holding(CANARY, since) or "checkpoints" in tables_holding(CANARY, since)
    assert "HTTP Request: POST" in logged(everything_logged)


def test_a_turn_without_the_header_runs_on_the_owners_key(upstream):
    with browser() as client:
        response = client.post(CHAT, json={"conversationId": "k2", "message": "你好"})
        # A key in the URL or the body is not a key: only the header is read.
        client.post(f"{CHAT}?x-model-key={KEY}&modelKey={KEY}",
                    json={"conversationId": "k3", "message": "你好", "modelKey": KEY, "x-model-key": KEY})
    evts = events(response)
    assert codes(evts) == [] and not any(e["type"] == "model" for e in evts)
    assert upstream.keys() == {OWNER_KEY}


@pytest.mark.parametrize("fail, code, says", [
    (401, "own_key_rejected", "没有接受"),
    (403, "own_key_rejected", "没有接受"),
    (402, "own_key_no_balance", "余额"),
    (429, "own_key_rate_limited", "限流"),
    (500, "own_key_provider_down", "没有响应"),
    ("hang", "own_key_provider_down", "没有响应"),
    (400, "own_key_request_refused", "HTTP 400"),
])
def test_a_failure_on_the_applicants_key_says_what_to_do_and_never_repeats_the_key(
        upstream, everything_logged, monkeypatch, fail, code, says):
    monkeypatch.setattr(llm, "MAX_RETRIES", 0)
    upstream.fail = fail
    since = transaction_mark()
    with browser() as client:
        response = client.post(CHAT, json={"conversationId": f"e{fail}", "message": "你好"}, headers=own())
    assert response.status_code == 200
    evts = events(response)
    assert codes(evts) == [code]
    message = next(e["message"] for e in evts if e["type"] == "error")
    assert says in message and "DeepSeek" in message
    assert evts[-1] == {"type": "done"}
    assert upstream.keys() == {KEY}
    assert_key_left_nowhere(KEY, response, everything_logged, since)
    # The failure is logged, by its kind.
    assert code in logged(everything_logged)


def test_the_same_failure_on_the_owners_key_keeps_its_own_words(upstream, monkeypatch):
    monkeypatch.setattr(llm, "MAX_RETRIES", 0)
    upstream.fail = 402
    with browser() as client:
        response = client.post(CHAT, json={"conversationId": "o1", "message": "你好"})
    assert codes(events(response)) == ["model_unavailable"]


def test_an_exception_that_prints_the_request_does_not_reach_the_log(upstream, everything_logged, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError(f"<Request('POST', 'https://api.deepseek.com/chat/completions') headers={{'authorization': 'Bearer {KEY}'}}>")

    async def intent_fixed(query, history):
        return {"intent": "业务操作", "confidence": 1.0}

    monkeypatch.setattr(graph_module, "get_chat_model", broken)
    monkeypatch.setattr(graph_module.intent, "classify", intent_fixed)
    since = transaction_mark()
    with browser() as client:
        response = client.post(CHAT, json={"conversationId": "x1", "message": "你好"}, headers=own())
    assert codes(events(response)) == ["advisor_failed"]
    assert "advisor stream failed" in logged(everything_logged)
    assert_key_left_nowhere(KEY, response, everything_logged, since)


# ---------- a paused turn ----------


def paused_turn(client: TestClient, upstream: Upstream, program: Program, conversation: str) -> dict:
    upstream.propose = program.id
    response = client.post(CHAT, json={"conversationId": conversation, "message": f"加入选校 {CANARY}"}, headers=own())
    confirm = next(e for e in events(response) if e["type"] == "confirm")
    return {"conversationId": conversation, "approved": False, "interruptId": confirm["id"]}


def test_a_turn_waiting_for_an_answer_holds_no_key(upstream, program, everything_logged):
    since = transaction_mark()
    with browser() as client:
        paused_turn(client, upstream, program, "p1")
        # While the turn waits, its whole state is in the checkpoint tables.
        assert tables_holding(KEY, since) == []
        assert redis_holding(KEY) == []
        assert set(tables_holding(CANARY, since)) & {"checkpoints", "checkpoint_blobs", "checkpoint_writes"}


def test_a_resumed_turn_takes_the_key_from_the_new_request(upstream, program, everything_logged):
    since = transaction_mark()
    with browser() as client:
        body = paused_turn(client, upstream, program, "p2")
        assert upstream.keys() == {KEY}
        upstream.seen.clear()
        response = client.post(CONFIRM, json=body, headers=own(OTHER_KEY, "siliconflow"))
    evts = events(response)
    assert codes(evts) == []
    assert evts[0] == {"type": "model", "ownKey": True, "provider": "siliconflow", "label": "硅基流动"}
    assert upstream.keys() == {OTHER_KEY}
    for key in (KEY, OTHER_KEY):
        assert_key_left_nowhere(key, response, everything_logged, since)


def test_a_turn_resumed_without_a_key_runs_on_the_owners(upstream, program):
    with browser() as client:
        body = paused_turn(client, upstream, program, "p3")
        upstream.seen.clear()
        response = client.post(CONFIRM, json=body)
    evts = events(response)
    assert codes(evts) == [] and not any(e["type"] == "model" for e in evts)
    assert upstream.keys() == {OWNER_KEY}


# ---------- limits ----------


def test_the_applicants_key_skips_the_daily_token_quotas(upstream, monkeypatch):
    monkeypatch.setattr(settings, "advisor_daily_tokens_per_subject", 0)
    monkeypatch.setattr(settings, "advisor_daily_tokens_per_ip", 0)
    monkeypatch.setattr(settings, "advisor_daily_tokens_site", 0)
    with browser() as client:
        refused = client.post(CHAT, json={"conversationId": "q1", "message": "你好"})
        assert refused.status_code == 429 and refused.json()["detail"]["code"].startswith("daily_tokens_")
        admitted = client.post(CHAT, json={"conversationId": "q2", "message": "你好"}, headers=own())
        assert admitted.status_code == 200 and codes(events(admitted)) == []
    assert upstream.keys() == {KEY}
    # Nothing was reserved on, or charged to, the owner's counters.
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    counters = [client.get(key) for key in client.scan_iter(match=settings.limits_key_prefix + "tokens:*")]
    assert all(int(value or 0) == 0 for value in counters)


def test_the_applicants_key_keeps_the_rate_windows(upstream, monkeypatch):
    monkeypatch.setattr(settings, "advisor_subject_limits", "1/60")
    with browser() as client:
        first = client.post(CHAT, json={"conversationId": "r1", "message": "你好"}, headers=own())
        second = client.post(CHAT, json={"conversationId": "r2", "message": "你好"}, headers=own())
    assert first.status_code == 200
    assert second.status_code == 429 and second.json()["detail"]["code"] == "rate_limited"
    assert KEY not in second.text


def test_a_ticket_without_quotas_reserves_nothing(monkeypatch):
    async def run():
        ticket = await limits.check("someone", "10.9.8.7", windows=True, quotas=False)
        usage = await limits.usage_today("someone", "10.9.8.7")
        # A confirm on the applicant's key takes no window and no quota, so it does not need the store.
        monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
        free = await limits.check("someone", "10.9.8.7", windows=False, quotas=False)
        return ticket, usage, free

    ticket, usage, free = asyncio.run(run())
    assert isinstance(ticket, limits.Ticket) and ticket.reserved == 0
    assert usage == {"subject": 0, "ip": 0, "site": 0}
    assert isinstance(free, limits.Ticket) and free.reserved == 0


# ---------- refusals before a turn ----------


@pytest.mark.parametrize("headers, code", [
    ({"X-Model-Key": KEY, "X-Model-Provider": "openai"}, "model_provider_unknown"),
    ({"X-Model-Key": KEY}, "model_provider_unknown"),
    ({"X-Model-Key": "has space " + KEY, "X-Model-Provider": "deepseek"}, "model_key_malformed"),
])
def test_a_bad_key_header_is_a_400_that_does_not_echo_it(upstream, everything_logged, headers, code):
    since = transaction_mark()
    with browser() as client:
        for path, body in ((CHAT, {"conversationId": "b1", "message": "你好"}),
                           (CONFIRM, {"conversationId": "b1", "approved": True}), (CHECK, None)):
            response = client.post(path, json=body, headers=headers)
            assert response.status_code == 400, path
            assert response.json()["detail"]["code"] == code
            assert_key_left_nowhere(KEY, response, everything_logged, since)
    assert upstream.seen == []


# ---------- embeddings ----------


def test_question_embeddings_stay_on_the_owners_key(upstream, monkeypatch):
    monkeypatch.setattr(settings, "embed_api_key", OWNER_EMBED_KEY)
    monkeypatch.setattr(settings, "embed_base_url", upstream.url)
    monkeypatch.setattr(settings, "advisor_retrieval", "hybrid")
    upstream.intent = "官方要求核验"
    with browser() as client:
        response = client.post(CHAT, json={"conversationId": "m1", "message": "悉尼大学计算机硕士的雅思要求"}, headers=own())
    assert response.status_code == 200
    assert upstream.keys("/embeddings") == {OWNER_EMBED_KEY}
    assert upstream.keys("/chat/completions") == {KEY}
    assert embeddings.configured_client() is not None


# ---------- trying a key ----------


def test_trying_a_key_lists_the_providers_models_and_spends_nothing(upstream, everything_logged):
    since = transaction_mark()
    with browser() as client:
        response = client.post(CHECK, headers=own())
    assert response.status_code == 200
    assert response.json() == {"ok": True, "provider": "deepseek", "label": "DeepSeek"}
    assert upstream.seen == [("/v1/models", KEY)]
    assert_key_left_nowhere(KEY, response, everything_logged, since)


@pytest.mark.parametrize("fail, code", [
    (401, "own_key_rejected"), (402, "own_key_no_balance"), (429, "own_key_rate_limited"),
    (503, "own_key_provider_down"), ("hang", "own_key_provider_down"),
])
def test_trying_a_key_that_fails_says_why(upstream, everything_logged, fail, code):
    upstream.fail = fail
    since = transaction_mark()
    with browser() as client:
        response = client.post(CHECK, headers=own())
    assert response.status_code == 200
    body = response.json()
    assert (body["ok"], body["code"]) == (False, code) and "DeepSeek" in body["message"]
    assert_key_left_nowhere(KEY, response, everything_logged, since)


def test_trying_a_key_needs_the_header_and_takes_a_rate_window(upstream, monkeypatch):
    monkeypatch.setattr(settings, "advisor_subject_limits", "1/60")
    with browser() as client:
        assert client.post(CHECK).status_code == 400
        assert client.post(CHECK, headers=own()).status_code == 200
        limited = client.post(CHECK, headers=own())
    assert limited.status_code == 429 and KEY not in limited.text
    assert len(upstream.seen) == 1


# ---------- signed out ----------


def test_signed_out_a_request_with_a_key_is_refused_and_the_key_is_not_logged(upstream, everything_logged, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    since = transaction_mark()
    with browser() as client:
        for path, body in ((CHAT, {"conversationId": "s1", "message": "你好"}), (CHECK, None)):
            response = client.post(path, json=body, headers=own())
            assert response.status_code == 401, path
            assert_key_left_nowhere(KEY, response, everything_logged, since)
    assert upstream.seen == []


# ---------- what sits in front of the API ----------


def test_the_reverse_proxy_keeps_no_access_log():
    """Caddy's access log would write request headers, this one included. It is off; if it is ever
    turned on, the key header has to be deleted from it first."""
    caddyfile = (Path(__file__).resolve().parents[2] / "deploy" / "Caddyfile").read_text()
    lines = [line.split("#")[0].strip() for line in caddyfile.splitlines()]
    assert not any(line == "log" or line.startswith("log ") or line.startswith("log{") for line in lines)
