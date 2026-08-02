from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import hmac
import inspect
import json
import logging
import os
import re
import secrets
from threading import RLock
from time import perf_counter
from typing import Any

from starlette.responses import PlainTextResponse, Response


logger = logging.getLogger("offerpilot.telemetry")

_TRACE_ID: ContextVar[str | None] = ContextVar("offerpilot_trace_id", default=None)
_SPAN_ID: ContextVar[str | None] = ContextVar("offerpilot_span_id", default=None)
_TRACEPARENT = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)
_DURATION_HISTOGRAM_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)
_RAG_RELEVANCE_SCORE_BUCKETS = (0.0, 4.0, 8.0, 16.0, 32.0, 64.0)


def _label_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(labels.items()))


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(labels: tuple[tuple[str, str], ...], extra: tuple[str, str] | None = None) -> str:
    values = [*labels, *([extra] if extra else [])]
    if not values:
        return ""
    return "{" + ",".join(f'{key}="{_escape_label(value)}"' for key, value in values) + "}"


class MetricRegistry:
    """Small, process-local Prometheus registry with bounded application labels."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histograms: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            tuple[tuple[float, ...], list[int], int, float],
        ] = {}

    def increment(self, name: str, labels: dict[str, str], value: float = 1.0) -> None:
        with self._lock:
            self._counters[(name, _label_key(labels))] += value

    def observe(
        self,
        name: str,
        labels: dict[str, str],
        value: float,
        *,
        buckets: tuple[float, ...] = _DURATION_HISTOGRAM_BUCKETS,
    ) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            existing = self._histograms.get(key)
            if existing is None:
                counts, count, total = [0] * len(buckets), 0, 0.0
            else:
                existing_buckets, counts, count, total = existing
                if existing_buckets != buckets:
                    raise ValueError(f"histogram {name} bucket boundaries changed")
            for index, boundary in enumerate(buckets):
                if value <= boundary:
                    counts[index] += 1
            self._histograms[key] = (buckets, counts, count + 1, total + value)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()

    def render(self) -> str:
        lines = [
            "# HELP offerpilot_http_requests_total Completed HTTP requests.",
            "# TYPE offerpilot_http_requests_total counter",
            "# HELP offerpilot_http_request_duration_seconds HTTP request duration.",
            "# TYPE offerpilot_http_request_duration_seconds histogram",
            "# HELP offerpilot_operation_total Completed traced operations.",
            "# TYPE offerpilot_operation_total counter",
            "# HELP offerpilot_operation_duration_seconds Traced operation duration.",
            "# TYPE offerpilot_operation_duration_seconds histogram",
            "# HELP offerpilot_rag_queries_total Official knowledge retrievals by grounded outcome.",
            "# TYPE offerpilot_rag_queries_total counter",
            "# HELP offerpilot_rag_top_relevance_score Highest BM25 relevance score per retrieval.",
            "# TYPE offerpilot_rag_top_relevance_score histogram",
        ]
        with self._lock:
            counters = sorted(self._counters.items())
            histograms = sorted(
                (key, (boundaries, list(counts), count, total))
                for key, (boundaries, counts, count, total) in self._histograms.items()
            )
        for (name, labels), value in counters:
            lines.append(f"{name}{_format_labels(labels)} {value:g}")
        for (name, labels), (boundaries, counts, count, total) in histograms:
            for boundary, bucket_count in zip(boundaries, counts, strict=True):
                lines.append(
                    f'{name}_bucket{_format_labels(labels, ("le", f"{boundary:g}"))} {bucket_count}'
                )
            lines.append(f'{name}_bucket{_format_labels(labels, ("le", "+Inf"))} {count}')
            lines.append(f"{name}_sum{_format_labels(labels)} {total:.9f}")
            lines.append(f"{name}_count{_format_labels(labels)} {count}")
        return "\n".join(lines) + "\n"


METRICS = MetricRegistry()


def current_trace_id() -> str | None:
    return _TRACE_ID.get()


def _parse_traceparent(value: str | None) -> tuple[str, str | None]:
    match = _TRACEPARENT.fullmatch((value or "").strip().lower())
    if not match:
        return secrets.token_hex(16), None
    trace_id = match.group("trace_id")
    parent_span_id = match.group("span_id")
    if trace_id == "0" * 32 or parent_span_id == "0" * 16:
        return secrets.token_hex(16), None
    return trace_id, parent_span_id


@contextmanager
def trace_scope(traceparent: str | None = None) -> Iterator[str]:
    trace_id, parent_span_id = _parse_traceparent(traceparent)
    trace_token = _TRACE_ID.set(trace_id)
    span_token = _SPAN_ID.set(parent_span_id)
    try:
        yield trace_id
    finally:
        _SPAN_ID.reset(span_token)
        _TRACE_ID.reset(trace_token)


@dataclass
class Span:
    name: str
    layer: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)

    def set_attribute(self, name: str, value: str | int | float | bool) -> None:
        self.attributes[name] = value


def _span_sampled(trace_id: str) -> bool:
    try:
        rate = float(os.getenv("TELEMETRY_SPAN_SAMPLE_RATE", "1.0"))
    except ValueError:
        rate = 1.0
    rate = min(1.0, max(0.0, rate))
    return int(trace_id[:8], 16) / 0xFFFFFFFF <= rate


@contextmanager
def trace_span(
    name: str,
    *,
    layer: str,
    attributes: dict[str, str | int | float | bool] | None = None,
) -> Iterator[Span]:
    owned_trace_token = None
    trace_id = _TRACE_ID.get()
    if trace_id is None:
        trace_id = secrets.token_hex(16)
        owned_trace_token = _TRACE_ID.set(trace_id)
    parent_span_id = _SPAN_ID.get()
    span = Span(
        name=name,
        layer=layer,
        trace_id=trace_id,
        span_id=secrets.token_hex(8),
        parent_span_id=parent_span_id,
        attributes=dict(attributes or {}),
    )
    span_token = _SPAN_ID.set(span.span_id)
    started = perf_counter()
    outcome = "success"
    error_type = None
    try:
        yield span
    except BaseException as error:
        outcome = "cancelled" if isinstance(error, GeneratorExit) else "error"
        error_type = None if isinstance(error, GeneratorExit) else type(error).__name__
        raise
    finally:
        duration_seconds = perf_counter() - started
        labels = {"layer": layer, "operation": name, "outcome": outcome}
        METRICS.increment("offerpilot_operation_total", labels)
        METRICS.observe("offerpilot_operation_duration_seconds", labels, duration_seconds)
        if _span_sampled(trace_id):
            payload: dict[str, Any] = {
                "event": "trace_span",
                "trace_id": trace_id,
                "span_id": span.span_id,
                "parent_span_id": parent_span_id,
                "name": name,
                "layer": layer,
                "outcome": outcome,
                "duration_ms": round(duration_seconds * 1000, 3),
                "attributes": span.attributes,
            }
            if error_type:
                payload["error_type"] = error_type
            logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        _SPAN_ID.reset(span_token)
        if owned_trace_token is not None:
            _TRACE_ID.reset(owned_trace_token)


def traced(name: str, *, layer: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Trace sync, async, and async-generator operations without recording arguments."""

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.isasyncgenfunction(function):
            @wraps(function)
            async def async_generator(*args: Any, **kwargs: Any):
                with trace_span(name, layer=layer):
                    async for item in function(*args, **kwargs):
                        yield item

            return async_generator
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def asynchronous(*args: Any, **kwargs: Any) -> Any:
                with trace_span(name, layer=layer):
                    return await function(*args, **kwargs)

            return asynchronous

        @wraps(function)
        def synchronous(*args: Any, **kwargs: Any) -> Any:
            with trace_span(name, layer=layer):
                return function(*args, **kwargs)

        return synchronous

    return decorate


def record_http_request(method: str, route: str, status_code: int, duration_seconds: float) -> None:
    labels = {
        "method": method.upper(),
        "route": route,
        "status_class": f"{status_code // 100}xx",
    }
    METRICS.increment("offerpilot_http_requests_total", labels)
    METRICS.observe("offerpilot_http_request_duration_seconds", labels, duration_seconds)


def record_rag_retrieval(hit_count: int, top_relevance_score: float | None) -> None:
    """Record retrieval quality signals without query, user, or program labels."""

    outcome = "hit" if hit_count > 0 else "no_answer"
    labels = {"outcome": outcome}
    METRICS.increment("offerpilot_rag_queries_total", labels)
    METRICS.observe(
        "offerpilot_rag_top_relevance_score",
        labels,
        max(0.0, top_relevance_score or 0.0),
        buckets=_RAG_RELEVANCE_SCORE_BUCKETS,
    )


_STORE_METHOD_PREFIXES = (
    "create_",
    "delete_",
    "get_",
    "list_",
    "reserve_",
    "review_",
    "save_",
    "set_",
    "update_",
)
_STORE_METHOD_NAMES = {
    "admin_counts",
    "admin_model_metrics",
    "healthcheck",
    "login",
    "logout",
    "register",
    "reset_password",
    "user_for_token",
    "verify_email",
}


def instrument_store(store: Any) -> Any:
    """Wrap persistence calls in-place while keeping adapter identity and behavior."""
    if getattr(store, "_offerpilot_telemetry_instrumented", False):
        return store
    adapter = store.__class__.__name__
    for method_name in dir(store):
        if method_name.startswith("_"):
            continue
        if method_name not in _STORE_METHOD_NAMES and not method_name.startswith(_STORE_METHOD_PREFIXES):
            continue
        original = getattr(store, method_name)
        if not callable(original):
            continue

        def instrumented(
            *args: Any,
            __method: Callable[..., Any] = original,
            __name: str = method_name,
            **kwargs: Any,
        ) -> Any:
            with trace_span(
                f"store.{__name}",
                layer="store",
                attributes={"store.adapter": adapter, "store.operation": __name},
            ):
                return __method(*args, **kwargs)

        setattr(store, method_name, wraps(original)(instrumented))
    setattr(store, "_offerpilot_telemetry_instrumented", True)
    return store


def metrics_response(authorization: str | None) -> Response:
    token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if not token:
        return PlainTextResponse("Not Found\n", status_code=404)
    supplied = authorization or ""
    expected = f"Bearer {token}"
    if not hmac.compare_digest(supplied, expected):
        return PlainTextResponse(
            "Unauthorized\n",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return PlainTextResponse(
        METRICS.render(),
        media_type="text/plain; version=0.0.4",
    )


def reset_telemetry_for_tests() -> None:
    METRICS.reset()


def configure_error_reporting() -> None:
    # Instrument the already-created adapter in-place so existing imports keep
    # the same object and readiness output keeps the concrete adapter name.
    from .store import store

    instrument_store(store)
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("APP_ENV", "development"),
        release=os.getenv("APP_RELEASE", "offerpilot-api@0.4.0"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
    )
