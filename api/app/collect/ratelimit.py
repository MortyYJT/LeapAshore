"""One request per host at a time, shared by every queue worker (openspec/changes/collect-queue, D3).

A token bucket with a capacity of one token per host, refilled every `interval` seconds, kept in Redis
so every worker process and machine using that Redis takes turns. Redis's own clock decides, so two
workers with skewed clocks cannot both think the turn is theirs. `www.x` and `x` share one bucket,
as they share a refusal.

A worker whose turn is more than `max_wait` seconds away does not sit on it: `RetryLater` tells the
task to put itself back on the queue with that countdown, freeing the worker for another host.
"""

import time

import redis

# KEYS[1] = the host's key; ARGV[1] = interval in milliseconds. Returns 0 when the token was taken,
# else the milliseconds until the next one. A refill that is not taken costs nothing.
_TAKE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local free_at = tonumber(redis.call('GET', KEYS[1]) or '0')
if now >= free_at then
  local interval = tonumber(ARGV[1])
  redis.call('SET', KEYS[1], now + interval, 'PX', interval * 2 + 1000)
  return 0
end
return free_at - now
"""


class RetryLater(Exception):
    """The host's next turn is further away than a worker should wait."""

    def __init__(self, host: str, delay: float) -> None:
        super().__init__(f"{host}: next request allowed in {delay:.1f}s")
        self.host = host
        self.delay = delay


def bucket_host(host: str) -> str:
    return host.lower().removeprefix("www.")


class HostBucket:
    """Callable as `limiter(host)`: returns once this process may send one request to `host`."""

    def __init__(self, client: redis.Redis, prefix: str, interval: float, max_wait: float = 10.0,
                 sleep=time.sleep) -> None:
        self.client = client
        self.prefix = prefix
        self.interval_ms = max(1, int(interval * 1000))
        self.max_wait = max_wait
        self.sleep = sleep
        self._take = client.register_script(_TAKE)

    def key(self, host: str) -> str:
        return f"{self.prefix}collect:host:{bucket_host(host)}"

    def try_take(self, host: str) -> float:
        """0 when the token was taken now; otherwise the seconds until the next one."""
        return int(self._take(keys=[self.key(host)], args=[self.interval_ms])) / 1000

    def __call__(self, host: str) -> None:
        while True:
            wait = self.try_take(host)
            if wait <= 0:
                return
            if wait > self.max_wait:
                raise RetryLater(host, wait)
            self.sleep(wait)
