from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
import json
import logging
import os
import re
from threading import Lock
from uuid import uuid4
from time import perf_counter

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .observability import (
    metrics_response,
    record_http_request,
    trace_scope,
    trace_span,
)


logger = logging.getLogger("offerpilot.request")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


def env_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def client_ip(request: Request) -> str:
    """Resolve an address without trusting client-controlled proxy headers by default."""
    direct = request.client.host if request.client else "unknown"
    if not env_enabled("TRUST_PROXY_HEADERS"):
        return direct
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or direct


class SecurityHeadersMiddleware:
    """Apply request security and telemetry across the complete response stream."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if _REQUEST_ID.fullmatch(supplied_request_id)
            else f"req_{uuid4().hex[:16]}"
        )
        request.state.request_id = request_id
        started = perf_counter()
        route = "__pre_route__"
        status_code = 500
        with trace_scope(request.headers.get("traceparent")) as trace_id:
            with trace_span(
                "http.request",
                layer="http",
                attributes={
                    "http.method": request.method,
                    "request.id": request_id,
                },
            ) as span:
                async def send_with_headers(message: Message) -> None:
                    nonlocal status_code
                    if message["type"] == "http.response.start":
                        status_code = message["status"]
                        headers = MutableHeaders(scope=message)
                        headers["X-Request-ID"] = request_id
                        headers["X-Trace-ID"] = trace_id
                        headers["X-Content-Type-Options"] = "nosniff"
                        headers["X-Frame-Options"] = "DENY"
                        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                        headers["Cache-Control"] = (
                            "no-store"
                            if request.url.path.startswith(("/auth", "/me", "/admin", "/internal"))
                            else "no-cache"
                        )
                    await send(message)

                try:
                    try:
                        content_length = int(request.headers.get("content-length", "0") or 0)
                    except ValueError:
                        content_length = 1_000_001
                    if request.url.path == "/internal/metrics":
                        route = "/internal/metrics"
                        response = metrics_response(request.headers.get("authorization"))
                        await response(scope, receive, send_with_headers)
                    elif content_length > 1_000_000:
                        response = JSONResponse({"detail": "请求内容过大"}, status_code=413)
                        await response(scope, receive, send_with_headers)
                    else:
                        await self.app(scope, receive, send_with_headers)
                    if route == "__pre_route__":
                        matched_route = scope.get("route")
                        route = getattr(matched_route, "path", None) or "__unmatched__"
                except BaseException:
                    if route == "__pre_route__":
                        matched_route = scope.get("route")
                        route = getattr(matched_route, "path", None) or "__unmatched__"
                    duration_seconds = perf_counter() - started
                    record_http_request(request.method, route, 500, duration_seconds)
                    span.set_attribute("http.route", route)
                    span.set_attribute("http.status_code", 500)
                    raise

                duration_seconds = perf_counter() - started
                span.set_attribute("http.route", route)
                span.set_attribute("http.status_code", status_code)
                record_http_request(request.method, route, status_code, duration_seconds)
                logger.info(json.dumps({
                    "event": "http_request", "request_id": request_id, "trace_id": trace_id,
                    "method": request.method, "route": route, "status": status_code,
                    "duration_ms": round(duration_seconds * 1000, 2),
                }, ensure_ascii=False))


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Single-instance Beta limiter; production can replace it with a shared Redis limiter."""

    def __init__(self, app: object) -> None:
        super().__init__(app)
        self._lock = Lock()
        self._requests: dict[str, deque[datetime]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS" or request.url.path.startswith("/health"):
            return await call_next(request)
        window = timedelta(minutes=1)
        limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
        if request.url.path.startswith("/auth/"):
            limit = int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "10"))
        client = client_ip(request)
        key = f"{client}:{request.url.path.split('/', 2)[:2]}"
        now = datetime.now(UTC)
        with self._lock:
            bucket = self._requests[key]
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                return JSONResponse(
                    {"detail": "请求过于频繁，请稍后重试"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            bucket.append(now)
        return await call_next(request)


class OriginGuardMiddleware(BaseHTTPMiddleware):
    """Reject cross-site mutations that rely on the browser session cookie."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        if "offerpilot_session" not in request.cookies or request.headers.get("authorization"):
            return await call_next(request)
        origin = request.headers.get("origin")
        if not origin:
            # Native clients and same-origin requests may not send Origin. SameSite=Lax
            # remains the browser baseline when the header is absent.
            return await call_next(request)
        allowed = {
            item.strip().rstrip("/")
            for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if item.strip()
        }
        if origin.rstrip("/") not in allowed:
            return JSONResponse({"detail": "请求来源未被允许"}, status_code=403)
        return await call_next(request)
