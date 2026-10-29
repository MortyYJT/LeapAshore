"""Advisor rate limits and token quotas, kept in Redis (openspec/changes/advisor-limits).

Two kinds of limit, both checked by one Lua script before a turn starts:

- Sliding windows (a sorted set of request times per subject and per IP, one key per window). The
  script records the request in every window only when every window and every cap passes, so a
  refused request never lengthens its own wait.
- Daily token caps per subject, per IP and for the whole site (a counter per Beijing day). An admitted
  turn reserves `ADVISOR_TURN_TOKEN_RESERVE` tokens on all three counters in the same script, so turns
  admitted side by side see each other before any of them has spent anything. Each model call's
  reported usage is added as it ends (`UsageRecorder`), and the reservation is returned when the turn
  ends (`settle`), leaving the counters at what was actually spent. A turn that costs more than the
  reservation can take a counter past its cap by the difference.

When Redis does not answer, `check` raises `LimitsUnavailable` and the advisor refuses with 503
(fail closed, D6): the advisor is the only endpoint that spends money.

A reply that times out does not mean the script did not run: Redis may have admitted the turn and
lost only the answer, and with no ticket nobody would `settle` the reservation. So every admission
carries an id, and a failed `check` withdraws it (`_WITHDRAW`, retried in the background when Redis
is still not answering): an admission that ran is undone, and one that has not run yet finds the id
withdrawn and admits nothing. Both scripts are idempotent, so a withdrawal whose own reply is lost can
be sent again.
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
# How long an admission id is remembered, which bounds how late a lost admission may still land.
RESERVATION_ID_TTL_SECONDS = 3600
# Background retries of a withdrawal whose first attempt failed, in seconds after the previous one.
WITHDRAW_RETRY_DELAYS: tuple[float, ...] = (1, 5, 30)

_WINDOW = re.compile(r"^(\d+)/(\d+)$")

# KEYS: 3 day counters (subject, ip, site), the admission id's key, then one sorted set per window.
# ARGV: 3 caps, the reservation, the request's member id, the window count, then (limit, span ms) per
# window, then the day counters' TTL, then the admission id's TTL.
# Returns {0, 0} when admitted (and reserved); {i, wait_ms} with i the 1-based KEYS index that refused;
# {-1, 0} when this admission was already withdrawn.
_CHECK = """
if redis.call('EXISTS', KEYS[4]) == 1 then
  return {-1, 0}
end
for i = 1, 3 do
  local used = tonumber(redis.call('GET', KEYS[i]) or '0')
  if used >= tonumber(ARGV[i]) then
    return {i, 0}
  end
end
local n = tonumber(ARGV[6])
local now = 0
if n > 0 then
  local t = redis.call('TIME')
  now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end
for j = 1, n do
  local key = KEYS[4 + j]
  local limit = tonumber(ARGV[5 + 2 * j])
  local span = tonumber(ARGV[6 + 2 * j])
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now - span)
  local count = redis.call('ZCARD', key)
  if count >= limit then
    if limit <= 0 then
      return {4 + j, span}
    end
    -- The entry whose expiry brings the count below the limit.
    local oldest = redis.call('ZRANGE', key, count - limit, count - limit, 'WITHSCORES')
    return {4 + j, span - (now - tonumber(oldest[2]))}
  end
end
for j = 1, n do
  local key = KEYS[4 + j]
  local span = tonumber(ARGV[6 + 2 * j])
  redis.call('ZADD', key, now, ARGV[5])
  redis.call('PEXPIRE', key, span)
end
local reserve = tonumber(ARGV[4])
local ttl = tonumber(ARGV[7 + 2 * n])
for i = 1, 3 do
  redis.call('INCRBY', KEYS[i], reserve)
  redis.call('EXPIRE', KEYS[i], ttl)
end
redis.call('SET', KEYS[4], 'admitted', 'EX', tonumber(ARGV[8 + 2 * n]))
return {0, 0}
"""

# KEYS: the admission id's key, the 3 day counters, then the window sorted sets.
# ARGV: the reservation, the request's member id, the admission id's TTL.
# Undoes an admission that ran (reservation and window entries) and marks the id withdrawn, so one
# still on its way is refused. Returns 1 when something was given back, else 0; safe to repeat.
_WITHDRAW = """
local state = redis.call('GET', KEYS[1])
if state == 'withdrawn' then
  return 0
end
redis.call('SET', KEYS[1], 'withdrawn', 'EX', tonumber(ARGV[3]))
if state ~= 'admitted' then
  return 0
end
local reserve = tonumber(ARGV[1])
for i = 2, 4 do
  if redis.call('EXISTS', KEYS[i]) == 1 then
    redis.call('DECRBY', KEYS[i], reserve)
  end
end
for j = 5, #KEYS do
  redis.call('ZREM', KEYS[j], ARGV[2])
end
return 1
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


@dataclass(frozen=True)
class Ticket:
    """An admitted turn: who it is charged to, and the reservation `settle` gives back."""

    subject: str
    ip: str
    day: str
    reserved: int


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


async def check(subject: str, ip: str | None, *, windows: bool = True) -> Ticket | Refusal:
    """A `Ticket` when the turn may run (its windows recorded, its tokens reserved), else why not.

    Raises `LimitsUnavailable` when Redis cannot be reached in time. Every ticket must be given to
    `settle` once the turn is over, or its reservation stays on today's counters.
    """
    ip = ip or "unknown"
    day = _day()
    p = settings.limits_key_prefix
    keys = _day_keys(subject, ip, day)
    reserve = max(0, settings.advisor_turn_token_reserve)
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
    member = uuid.uuid4().hex
    admission = f"{p}admission:{member}"
    window_keys = [k for k, _, _ in spans]
    argv: list[Any] = [*caps, reserve, member, len(spans)]
    for _key, limit, span_ms in spans:
        argv += [limit, span_ms]
    argv += [DAY_KEY_TTL_SECONDS, RESERVATION_ID_TTL_SECONDS]
    try:
        index, wait_ms = await _client().eval(_CHECK, 4 + len(spans), *keys, admission, *window_keys, *argv)
    except (RedisError, OSError, asyncio.TimeoutError) as error:
        # The script may have run with only its reply lost; nobody holds a ticket to settle it.
        await _withdraw_soon([admission, *keys, *window_keys], reserve, member)
        raise LimitsUnavailable(str(error)) from error
    index, wait_ms = int(index), int(wait_ms)
    if index < 0:
        raise LimitsUnavailable("the admission arrived after it was withdrawn")
    if index == 0:
        return Ticket(subject=subject, ip=ip, day=day, reserved=reserve)
    if index <= 3:
        scope = ("subject", "ip", "site")[index - 1]
        return Refusal(f"daily_tokens_{scope}", _CAP_MESSAGES[scope], seconds_until_tomorrow())
    wait = max(1, -(-wait_ms // 1000))
    return Refusal("rate_limited", f"发送太频繁了，请 {wait} 秒后再试。", wait)


# Withdrawals still being retried, kept so the tasks are not garbage-collected mid-run.
_withdrawals: set[asyncio.Task] = set()


async def _withdraw(keys: list[str], reserve: int, member: str) -> None:
    await _client().eval(_WITHDRAW, len(keys), *keys, reserve, member, RESERVATION_ID_TTL_SECONDS)


async def _withdraw_soon(keys: list[str], reserve: int, member: str) -> None:
    """Withdraw an admission now; if Redis still does not answer, keep trying in the background."""
    try:
        await _withdraw(keys, reserve, member)
        return
    except (RedisError, OSError, asyncio.TimeoutError):
        pass

    async def retry() -> None:
        for delay in WITHDRAW_RETRY_DELAYS:
            await asyncio.sleep(delay)
            try:
                await _withdraw(keys, reserve, member)
                return
            except (RedisError, OSError, asyncio.TimeoutError):
                continue
        logger.error(
            "could not withdraw advisor admission %s; up to %d tokens stay reserved today", member, reserve
        )

    task = asyncio.create_task(retry())
    _withdrawals.add(task)
    task.add_done_callback(_withdrawals.discard)


async def _add(keys: list[str], tokens: int) -> None:
    try:
        async with _client().pipeline(transaction=True) as pipe:
            for key in keys:
                pipe.incrby(key, tokens)
                pipe.expire(key, DAY_KEY_TTL_SECONDS)
            await pipe.execute()
    except (RedisError, OSError, asyncio.TimeoutError) as error:
        raise LimitsUnavailable(str(error)) from error


async def record_usage(subject: str, ip: str | None, tokens: int) -> None:
    """Add `tokens` to today's subject, IP and site counters. Raises `LimitsUnavailable`."""
    if tokens > 0:
        await _add(_day_keys(subject, ip or "unknown", _day()), tokens)


async def settle(ticket: Ticket) -> None:
    """Give back a ticket's reservation, on the day it was taken. Failures are logged."""
    if ticket.reserved <= 0:
        return
    try:
        await _add(_day_keys(ticket.subject, ticket.ip, ticket.day), -ticket.reserved)
    except LimitsUnavailable:
        logger.exception("could not return a reservation of %d advisor tokens", ticket.reserved)


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
