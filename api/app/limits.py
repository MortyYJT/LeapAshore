"""Advisor rate limits and token quotas, kept in Redis (openspec/changes/advisor-limits).

Two kinds of limit, both checked by one Lua script before a turn starts:

- Sliding windows (a sorted set of request times per subject and per IP, one key per window). The
  script records the request in every window only when every window and every cap passes, so a
  refused request never lengthens its own wait.
- Daily token caps per subject, per IP and for the whole site (a counter per Beijing day). The model's
  reported usage is added after each call by `UsageRecorder`, so a turn that starts under a cap may end
  over it by at most one turn's worth.

When Redis does not answer, `check` raises `LimitsUnavailable` and the advisor refuses with 503
(fail closed, D6): the advisor is the only endpoint that spends money.
"""

import asyncio
import logging
import re
import uuid
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import redis.asyncio as aioredis
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)

# The applicants are in China, so "a day" ends at midnight Beijing time. No DST, so a fixed offset.
BEIJING = timezone(timedelta(hours=8))
# A day counter outlives its day by one more, so yesterday's total is still there to look at.
DAY_KEY_TTL_SECONDS = 2 * 24 * 3600
REDIS_TIMEOUT_SECONDS = 0.5

_WINDOW = re.compile(r"^(\d+)/(\d+)$")

# KEYS: 3 day counters (subject, ip, site), then one sorted set per window.
# ARGV: 3 caps, the request's member id, the window count, then (limit, span ms) per window.
# Returns {0, 0} when allowed; {i, wait_ms} with i the 1-based KEYS index that refused otherwise.
_CHECK = """
for i = 1, 3 do
  local used = tonumber(redis.call('GET', KEYS[i]) or '0')
  if used >= tonumber(ARGV[i]) then
    return {i, 0}
  end
end
local n = tonumber(ARGV[5])
if n == 0 then
  return {0, 0}
end
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
for j = 1, n do
  local key = KEYS[3 + j]
  local limit = tonumber(ARGV[4 + 2 * j])
  local span = tonumber(ARGV[5 + 2 * j])
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now - span)
  local count = redis.call('ZCARD', key)
  if count >= limit then
    if limit <= 0 then
      return {3 + j, span}
    end
    -- The entry whose expiry brings the count below the limit.
    local oldest = redis.call('ZRANGE', key, count - limit, count - limit, 'WITHSCORES')
    return {3 + j, span - (now - tonumber(oldest[2]))}
  end
end
for j = 1, n do
  local key = KEYS[3 + j]
  local span = tonumber(ARGV[5 + 2 * j])
  redis.call('ZADD', key, now, ARGV[4])
  redis.call('PEXPIRE', key, span)
end
return {0, 0}
"""

UNAVAILABLE = "顾问暂时不可用，请稍后再试。"
_CAP_MESSAGES = {
    "subject": "你今天的顾问额度已用完，北京时间明天 0 点恢复。",
    "ip": "你所在网络今天的顾问额度已用完，北京时间明天 0 点恢复。",
    "site": "今天全站的顾问额度已用完，北京时间明天 0 点恢复。",
}


class LimitsUnavailable(RuntimeError):
    """Redis did not answer; the caller refuses rather than spend without a limit."""


@dataclass(frozen=True)
class Refusal:
    code: str
    message: str
    retry_after: int

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, "retryAfter": self.retry_after}


def parse_windows(spec: str) -> list[tuple[int, int]]:
    """`"10/60,60/3600"` -> `[(10, 60), (60, 3600)]`: requests per seconds. Empty means none."""
    windows = []
    for part in spec.split(","):
        part = part.strip().replace(" ", "")
        if not part:
            continue
        match = _WINDOW.match(part)
        if not match or int(match.group(2)) <= 0:
            raise ValueError(f"bad limit window {part!r}; expected requests/seconds, e.g. 10/60")
        windows.append((int(match.group(1)), int(match.group(2))))
    return windows


# One client per event loop and URL: a redis.asyncio connection belongs to the loop that opened it,
# and the test client runs each app instance on its own loop.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, aioredis.Redis]]" = (
    weakref.WeakKeyDictionary()
)


def _client() -> aioredis.Redis:
    per_loop = _clients.setdefault(asyncio.get_running_loop(), {})
    client = per_loop.get(settings.redis_url)
    if client is None:
        client = aioredis.Redis.from_url(
            settings.redis_url,
            socket_timeout=REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
            decode_responses=True,
        )
        per_loop[settings.redis_url] = client
    return client


def _day(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(BEIJING).strftime("%Y%m%d")


def seconds_until_tomorrow(now: datetime | None = None) -> int:
    local = (now or datetime.now(UTC)).astimezone(BEIJING)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - local).total_seconds()))


def _day_keys(subject: str, ip: str, day: str) -> list[str]:
    p = settings.limits_key_prefix
    return [f"{p}tokens:subject:{subject}:{day}", f"{p}tokens:ip:{ip}:{day}", f"{p}tokens:site:{day}"]


async def check(subject: str, ip: str | None, *, windows: bool = True) -> Refusal | None:
    """None when the turn may run (and, with `windows`, record it); otherwise why not.

    Raises `LimitsUnavailable` when Redis cannot be reached in time.
    """
    ip = ip or "unknown"
    p = settings.limits_key_prefix
    keys = _day_keys(subject, ip, _day())
    caps = [
        settings.advisor_daily_tokens_per_subject,
        settings.advisor_daily_tokens_per_ip,
        settings.advisor_daily_tokens_site,
    ]
    spans: list[tuple[str, int, int]] = []
    if windows:
        for scope, ident, spec in (
            ("subject", subject, settings.advisor_subject_limits),
            ("ip", ip, settings.advisor_ip_limits),
        ):
            for limit, seconds in parse_windows(spec):
                spans.append((f"{p}win:{scope}:{ident}:{seconds}", limit, seconds * 1000))
    argv: list[Any] = [*caps, uuid.uuid4().hex, len(spans)]
    for _key, limit, span_ms in spans:
        argv += [limit, span_ms]
    try:
        index, wait_ms = await _client().eval(_CHECK, 3 + len(spans), *keys, *(k for k, _, _ in spans), *argv)
    except (RedisError, OSError, asyncio.TimeoutError) as error:
        raise LimitsUnavailable(str(error)) from error
    index, wait_ms = int(index), int(wait_ms)
    if index == 0:
        return None
    if index <= 3:
        scope = ("subject", "ip", "site")[index - 1]
        return Refusal(f"daily_tokens_{scope}", _CAP_MESSAGES[scope], seconds_until_tomorrow())
    wait = max(1, -(-wait_ms // 1000))
    return Refusal("rate_limited", f"发送太频繁了，请 {wait} 秒后再试。", wait)


async def record_usage(subject: str, ip: str | None, tokens: int) -> None:
    """Add `tokens` to today's subject, IP and site counters. Raises `LimitsUnavailable`."""
    if tokens <= 0:
        return
    try:
        async with _client().pipeline(transaction=True) as pipe:
            for key in _day_keys(subject, ip or "unknown", _day()):
                pipe.incrby(key, tokens)
                pipe.expire(key, DAY_KEY_TTL_SECONDS)
            await pipe.execute()
    except (RedisError, OSError, asyncio.TimeoutError) as error:
        raise LimitsUnavailable(str(error)) from error


async def usage_today(subject: str, ip: str | None) -> dict[str, int]:
    values = await _client().mget(_day_keys(subject, ip or "unknown", _day()))
    return {scope: int(v or 0) for scope, v in zip(("subject", "ip", "site"), values, strict=True)}


def _tokens_of(response: LLMResult) -> int:
    """The total the provider reported for one call: per-message usage, else the `token_usage` block."""
    total = 0
    for generations in response.generations:
        for generation in generations:
            usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
            if usage:
                total += int(usage.get("total_tokens") or 0)
    if total == 0 and response.llm_output:
        usage = response.llm_output.get("token_usage") or {}
        total = int(usage.get("total_tokens") or 0)
    return total


class UsageRecorder(AsyncCallbackHandler):
    """Charges each finished model call of one turn to its subject, IP and the site.

    Passed in the graph config's callbacks, so every model call inside the turn (the intent router and
    each agent step) reports here as it ends. A failure to record is logged: the tokens are spent.
    """

    def __init__(self, subject: str, ip: str | None) -> None:
        self.subject = subject
        self.ip = ip

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        tokens = _tokens_of(response)
        if tokens <= 0:
            logger.warning("model call ended without reported token usage; not counted")
            return
        try:
            await record_usage(self.subject, self.ip, tokens)
        except LimitsUnavailable:
            logger.exception("could not record %d advisor tokens", tokens)
