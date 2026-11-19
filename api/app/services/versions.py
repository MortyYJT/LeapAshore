"""Refusing a stale update (`docs/product/PRD-multi-device.md`, 3.3).

An update states the version it was based on. The route locks what it is about to write, compares
that version with the stored one, and answers a mismatch with 409 and the record as the server holds
it, so the client can show both sides and let the applicant choose. Nothing is written for a refused
update.

Single rows (a roadmap task, the profile) use the row's integer `version`. An application record is
read from up to two rows and the portfolio is a set of rows, so their versions are derived:
`token_of` for a record, and the `(id, version)` pairs of the rows for the portfolio. The row ids are
part of both, so a row that was removed and created again never repeats an earlier version.
"""

import hashlib
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

STALE_CODE = "stale_version"
STALE_DETAIL = "这条记录已在其他设备上修改。"


class StaleVersion(Exception):
    """An update was based on a version the server no longer holds. Carries the current row."""

    def __init__(self, current: Any) -> None:
        super().__init__(STALE_DETAIL)
        self.current = current


def stale_response(current: Any) -> JSONResponse:
    """The 409 for a stale update: a message, a code the client branches on, and the server state."""
    return JSONResponse(
        status_code=409,
        content=jsonable_encoder(
            {"detail": STALE_DETAIL, "code": STALE_CODE, "current": current}
        ),
    )


def token_of(*rows: Any) -> str:
    """One opaque version for a record built from several rows; `None` stands for an absent row."""
    parts = ["-" if row is None else f"{row.id}:{row.version}" for row in rows]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
