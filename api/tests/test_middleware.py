"""The body limit that has to run before anything reads the body.

The point of this middleware is not the status code — the upload service also refuses an oversize
file — but *when* it refuses. Starlette spools a multipart body to a temporary file before an endpoint
runs, so an endpoint-level limit still lets the whole request land on disk first. These tests assert
the wrapped application is never entered at all.
"""

import asyncio

from app.middleware import BodySizeLimitMiddleware


def drive(*, method: str, path: str, headers: list[tuple[bytes, bytes]], max_bytes: int = 10):
    """Run one request through the middleware and return (paths that reached the app, messages)."""
    reached: list[str] = []
    messages: list[dict] = []

    async def inner(scope, receive, send):
        reached.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    middleware = BodySizeLimitMiddleware(
        inner, max_bytes=max_bytes, paths=("/api/documents",), detail="太大"
    )
    asyncio.run(
        middleware(
            {"type": "http", "method": method, "path": path, "headers": headers}, receive, send
        )
    )
    return reached, messages


def test_a_declared_oversize_body_never_reaches_the_app():
    reached, messages = drive(
        method="POST",
        path="/api/documents",
        headers=[(b"content-length", b"11")],
    )

    assert reached == [], "the body was read before it was refused"
    assert messages[0]["status"] == 413


def test_a_body_within_the_limit_is_left_alone():
    reached, messages = drive(
        method="POST",
        path="/api/documents",
        headers=[(b"content-length", b"10")],
    )

    assert reached == ["/api/documents"]
    assert messages[0]["status"] == 200


def test_another_path_is_left_alone():
    reached, _ = drive(
        method="POST",
        path="/api/applications",
        headers=[(b"content-length", str(1 << 30).encode())],
    )

    assert reached == ["/api/applications"]


def test_a_request_without_a_declared_length_is_left_alone():
    """A chunked body declares no length; the counting copy in the service is what bounds it."""
    reached, _ = drive(method="POST", path="/api/documents", headers=[])

    assert reached == ["/api/documents"]


def test_a_get_is_left_alone():
    reached, _ = drive(
        method="GET",
        path="/api/documents",
        headers=[(b"content-length", str(1 << 30).encode())],
    )

    assert reached == ["/api/documents"]
