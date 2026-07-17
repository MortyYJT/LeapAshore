from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
import json
import logging
import os
from threading import Lock
from uuid import uuid4
from time import perf_counter

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


logger = logging.getLogger("offerpilot.request")


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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id", f"req_{uuid4().hex[:16]}")[:80]
        request.state.request_id = request_id
        started = perf_counter()
        try:
            content_length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            content_length = 1_000_001
        if content_length > 1_000_000:
            return JSONResponse({"detail": "请求内容过大"}, status_code=413, headers={"X-Request-ID": request_id})
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/auth", "/me", "/admin")) else "no-cache"
        logger.info(json.dumps({
            "event": "http_request", "request_id": request_id, "method": request.method,
            "path": request.url.path, "status": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        }, ensure_ascii=False))
        return response


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
