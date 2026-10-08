"""Limits that have to be applied before the request body is read.

A size limit enforced inside an endpoint is not a limit on what the server accepts: Starlette parses
a multipart body into a spooled temporary file before the endpoint body runs, so by the time the
upload service can count the bytes they are already on disk in the system temp directory. This
middleware turns a *declared* oversize into a 413 first. A body that lies about its declared length
is still caught by the counting copy in `app.services.documents`, which is the rule that actually
bounds what reaches the storage root.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def _content_length(headers: list[tuple[bytes, bytes]]) -> int | None:
    """The declared body length, or None when it is absent or not a number."""
    for name, value in headers:
        if name.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class BodySizeLimitMiddleware:
    """Refuse an oversize declared body on the paths that accept uploads, without reading it."""

    def __init__(self, app: ASGIApp, *, max_bytes: int, paths: tuple[str, ...], detail: str) -> None:
        self.app = app
        self.max_bytes = max_bytes
        # A prefix tuple, not a route pattern: this runs before routing, and `POST` is the only method
        # any of these paths accepts a body on. Everything else is left alone, including the GETs
        # that read a large-ish JSON response.
        self.paths = paths
        self.detail = detail

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST":
            if scope["path"].startswith(self.paths):
                length = _content_length(scope["headers"])
                if length is not None and length > self.max_bytes:
                    response = JSONResponse({"detail": self.detail}, status_code=413)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
