"""Keeping the unsubscribe token out of the access log.

A mail client acting on `List-Unsubscribe-Post` can only send the token in the URL, and uvicorn
writes every request line, query string included, to `uvicorn.access`. This filter rewrites that one
route's line before any handler sees it.
"""

import logging
import re

_TOKEN = re.compile(r"(/api/reminders/unsubscribe\?(?:[^\s\"]*&)?token=)[^&\s\"]*")


def redact(path: str) -> str:
    return _TOKEN.sub(r"\1[redacted]", path)


class RedactUnsubscribeToken(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) if isinstance(arg, str) else arg for arg in record.args)
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


def install() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, RedactUnsubscribeToken) for existing in logger.filters):
        logger.addFilter(RedactUnsubscribeToken())
