from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
import pytest

from app.middleware import SecurityHeadersMiddleware
from app.models import ApplicantProfile, KnowledgeSearchRequest
from app.observability import (
    METRICS,
    instrument_store,
    reset_telemetry_for_tests,
    trace_scope,
    traced,
)
from app.services.advisor import plan_turn
from app.services.deepseek_advisor import DeepSeekStreamError, safe_tool_actions, stream_deepseek
from app.services.knowledge_rag import retrieve_official_knowledge
from app.services.model_provider import ModelProviderError, plan_advisor_turn


def telemetry_app() -> FastAPI:
    app = FastAPI()

    @app.get("/programs/{program_slug}")
    def program(program_slug: str) -> dict[str, int]:
        response = retrieve_official_knowledge(KnowledgeSearchRequest(
            query=f"{program_slug} 成绩要求",
            program_slugs=[program_slug],
            top_k=3,
        ))
        return {"hits": len(response.hits)}

    @traced("provider.test_stream", layer="provider")
    async def stream_chunks():
        yield b"first\n"
        await asyncio.sleep(0)
        yield b"second\n"

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        return StreamingResponse(stream_chunks(), media_type="text/plain")

    app.add_middleware(SecurityHeadersMiddleware)
    return app


def test_metrics_endpoint_is_disabled_without_a_token_and_rejects_wrong_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_telemetry_for_tests()
    monkeypatch.delenv("METRICS_BEARER_TOKEN", raising=False)
    client = TestClient(telemetry_app())

    disabled = client.get("/internal/metrics")
    assert disabled.status_code == 404
    assert disabled.headers["cache-control"] == "no-store"

    monkeypatch.setenv("METRICS_BEARER_TOKEN", "metrics-test-token")
    rejected = client.get(
        "/internal/metrics",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert rejected.status_code == 401
    assert rejected.headers["www-authenticate"] == "Bearer"
    assert "metrics-test-token" not in rejected.text


def test_http_and_rag_spans_share_trace_and_metrics_use_route_templates(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    reset_telemetry_for_tests()
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "metrics-test-token")
    caplog.set_level(logging.INFO, logger="offerpilot.telemetry")
    client = TestClient(telemetry_app())
    trace_id = "1" * 32

    response = client.get(
        "/programs/unsw-master-it",
        headers={"traceparent": f"00-{trace_id}-{'2' * 16}-01"},
    )
    assert response.status_code == 200
    assert response.headers["x-trace-id"] == trace_id

    metrics = client.get(
        "/internal/metrics",
        headers={"Authorization": "Bearer metrics-test-token"},
    )
    assert metrics.status_code == 200
    assert (
        'offerpilot_http_requests_total{method="GET",route="/programs/{program_slug}",status_class="2xx"} 1'
        in metrics.text
    )
    assert (
        'offerpilot_operation_total{layer="rag",operation="rag.retrieve",outcome="success"} 1'
        in metrics.text
    )
    assert "unsw-master-it" not in metrics.text

    spans = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "offerpilot.telemetry"
    ]
    request_span = next(item for item in spans if item["name"] == "http.request" and item["trace_id"] == trace_id)
    rag_span = next(item for item in spans if item["name"] == "rag.retrieve" and item["trace_id"] == trace_id)
    assert rag_span["parent_span_id"] == request_span["span_id"]
    assert request_span["attributes"]["http.route"] == "/programs/{program_slug}"


def test_unmatched_routes_do_not_create_high_cardinality_metric_labels(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    reset_telemetry_for_tests()
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "metrics-test-token")
    caplog.set_level(logging.INFO, logger="offerpilot.request")
    client = TestClient(telemetry_app())

    response = client.get(
        "/missing/private-user-123",
        headers={"X-Request-ID": "private@example.com"},
    )
    assert response.status_code == 404
    assert response.headers["x-request-id"].startswith("req_")
    metrics = client.get(
        "/internal/metrics",
        headers={"Authorization": "Bearer metrics-test-token"},
    ).text
    assert 'route="__unmatched__"' in metrics
    assert "private-user-123" not in metrics
    assert "private@example.com" not in "\n".join(record.message for record in caplog.records)


def test_stream_span_stays_inside_request_trace_until_body_completion(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reset_telemetry_for_tests()
    caplog.set_level(logging.INFO, logger="offerpilot.telemetry")
    client = TestClient(telemetry_app())
    trace_id = "3" * 32

    response = client.get(
        "/stream",
        headers={"traceparent": f"00-{trace_id}-{'4' * 16}-01"},
    )
    assert response.status_code == 200
    assert response.text == "first\nsecond\n"

    spans = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "offerpilot.telemetry"
    ]
    request_span = next(item for item in spans if item["name"] == "http.request")
    provider_span = next(item for item in spans if item["name"] == "provider.test_stream")
    assert request_span["trace_id"] == trace_id
    assert provider_span["trace_id"] == trace_id
    assert provider_span["parent_span_id"] == request_span["span_id"]
    assert provider_span["duration_ms"] <= request_span["duration_ms"]


def test_store_instrumentation_records_failures_without_serializing_arguments(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    reset_telemetry_for_tests()
    monkeypatch.setenv("TELEMETRY_SPAN_SAMPLE_RATE", "1")
    caplog.set_level(logging.INFO, logger="offerpilot.telemetry")

    class FailingStore:
        def save_profile(self, user_id: str, profile: dict[str, str]) -> None:
            raise RuntimeError(f"should not be logged: {user_id} {profile['email']}")

    store = instrument_store(FailingStore())
    with trace_scope():
        with pytest.raises(RuntimeError):
            store.save_profile("secret-user", {"email": "private@example.com"})

    spans = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "offerpilot.telemetry"
    ]
    store_span = next(item for item in spans if item["name"] == "store.save_profile")
    assert store_span["outcome"] == "error"
    assert store_span["error_type"] == "RuntimeError"
    rendered = json.dumps(store_span, ensure_ascii=False)
    assert "secret-user" not in rendered
    assert "private@example.com" not in rendered


def test_advisor_and_provider_success_and_error_paths_are_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_telemetry_for_tests()
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    profile = ApplicantProfile(
        undergraduate_school="测试大学",
        school_tier="双非",
        undergraduate_major="软件工程",
        gpa=82,
        gpa_scale=100,
        target_field="计算机与数据",
    )

    with trace_scope():
        reply, actions, metadata = plan_turn("我还缺哪些材料？", profile, [])
        planned_actions = safe_tool_actions("我还缺哪些材料？", profile, None, [])
        with pytest.raises(ModelProviderError):
            plan_advisor_turn({"user_message": "不会离开本机"})

        async def consume_stream() -> None:
            async for _ in stream_deepseek({"user_message": "不会发起请求"}):
                pass

        with pytest.raises(DeepSeekStreamError):
            asyncio.run(consume_stream())

    assert reply
    assert actions
    assert planned_actions
    assert metadata["provider"] == "deterministic-fallback"
    metrics = METRICS.render()
    assert (
        'offerpilot_operation_total{layer="agent",operation="advisor.plan",outcome="success"} 1'
        in metrics
    )
    assert (
        'offerpilot_operation_total{layer="agent",operation="advisor.actions.plan",outcome="success"} 1'
        in metrics
    )
    assert (
        'offerpilot_operation_total{layer="provider",operation="provider.plan",outcome="error"} 1'
        in metrics
    )
    assert (
        'offerpilot_operation_total{layer="provider",operation="provider.stream",outcome="error"} 1'
        in metrics
    )
