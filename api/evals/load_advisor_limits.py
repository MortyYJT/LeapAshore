"""Load test for the advisor limits (openspec/changes/advisor-limits). Local only; never calls a model.

Two measurements:

``--mode check`` calls `app.limits.check` in-process against the Redis in `REDIS_URL`: `--requests`
checks from `--concurrency` tasks, spread round-robin over `--subjects` subjects and `--ips` IPs, with
the configured windows. Reports the latency of the check (p50/p95/p99/max) and the blocked ratio, and
compares the admitted count with the most the windows allow, which is how a race in the script would
show.

``--mode http`` sends the same pattern to ``POST /api/advisor/chat`` on `--base-url` (start a server
with `CHAT_API_KEY=` empty, `AUTH_ENABLED=false` and `TRUSTED_PROXIES=127.0.0.1`, so admitted turns
end at once and `X-Forwarded-For` picks the IP). No cookie is sent, so every request is a new
anonymous subject: the pattern of a client that drops its cookie. Reports status counts and the
end-to-end latency.

    cd api && .venv/bin/python -m evals.load_advisor_limits --mode check
    cd api && .venv/bin/python -m evals.load_advisor_limits --mode http --base-url http://127.0.0.1:8100
"""

import argparse
import asyncio
import statistics
import time
import uuid

from app import limits
from app.config import settings


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summary(label: str, latencies_ms: list[float]) -> str:
    return (
        f"{label}: n={len(latencies_ms)} p50={percentile(latencies_ms, 0.50):.2f}ms "
        f"p95={percentile(latencies_ms, 0.95):.2f}ms p99={percentile(latencies_ms, 0.99):.2f}ms "
        f"max={max(latencies_ms):.2f}ms mean={statistics.fmean(latencies_ms):.2f}ms"
    )


def ceiling(subjects: int, ips: int, requests: int) -> int:
    """The most the shortest windows can admit within one run, if the run is shorter than them."""
    subject_cap = min(limit for limit, _ in limits.parse_windows(settings.advisor_subject_limits))
    ip_cap = min(limit for limit, _ in limits.parse_windows(settings.advisor_ip_limits))
    # Requests go round-robin, so each IP's subjects are distinct; the IP window binds unless the
    # subjects behind one IP together allow fewer.
    per_ip = min(ip_cap, subject_cap * max(1, subjects // ips))
    return min(requests, per_ip * ips)


async def run_check(args) -> None:
    settings.limits_key_prefix = f"load:{uuid.uuid4().hex[:8]}:"
    subjects = [str(uuid.uuid4()) for _ in range(args.subjects)]
    ips = [f"10.99.{i // 250}.{i % 250 + 1}" for i in range(args.ips)]
    queue: asyncio.Queue[int] = asyncio.Queue()
    for n in range(args.requests):
        queue.put_nowait(n)
    latencies: list[float] = []
    blocked = 0

    async def worker() -> None:
        nonlocal blocked
        while True:
            try:
                n = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            started = time.perf_counter()
            refusal = await limits.check(subjects[n % len(subjects)], ips[n % len(ips)])
            latencies.append((time.perf_counter() - started) * 1000)
            blocked += refusal is not None

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(args.concurrency)))
    elapsed = time.perf_counter() - started
    admitted = args.requests - blocked
    print(
        f"windows subject={settings.advisor_subject_limits} ip={settings.advisor_ip_limits}; "
        f"{args.requests} checks, {args.concurrency} concurrent, {args.subjects} subjects, {args.ips} IPs, "
        f"{elapsed:.2f}s ({args.requests / elapsed:.0f}/s)"
    )
    print(f"admitted={admitted} (ceiling {ceiling(args.subjects, args.ips, args.requests)}) blocked={blocked} "
          f"blocked_ratio={blocked / args.requests:.4f}")
    print(summary("limit check", latencies))
    client = limits._client()
    keys = [key async for key in client.scan_iter(match=settings.limits_key_prefix + "*", count=1000)]
    if keys:
        await client.delete(*keys)


async def run_http(args) -> None:
    import httpx

    ips = [f"10.98.{i // 250}.{i % 250 + 1}" for i in range(args.ips)]
    statuses: dict[int, int] = {}
    latencies: list[float] = []
    queue: asyncio.Queue[int] = asyncio.Queue()
    for n in range(args.requests):
        queue.put_nowait(n)

    async def worker(client: httpx.AsyncClient) -> None:
        while True:
            try:
                n = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            started = time.perf_counter()
            response = await client.post(
                "/api/advisor/chat",
                json={"conversationId": "load", "message": "你好"},
                headers={"X-Forwarded-For": ips[n % len(ips)]},
            )
            await response.aread()
            latencies.append((time.perf_counter() - started) * 1000)
            statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
            client.cookies.clear()

    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as probe:
        clients = [httpx.AsyncClient(base_url=args.base_url, timeout=30) for _ in range(args.concurrency)]
        await asyncio.gather(*(worker(c) for c in clients))
        for c in clients:
            await c.aclose()
        await probe.get("/api/health")
    elapsed = time.perf_counter() - started
    blocked = statuses.get(429, 0)
    print(f"{args.requests} requests, {args.concurrency} concurrent, {args.ips} IPs, no cookies, {elapsed:.2f}s")
    print(f"statuses={dict(sorted(statuses.items()))} blocked_ratio={blocked / args.requests:.4f} "
          f"(ceiling {args.ips} IPs x shortest IP window)")
    print(summary("end to end", latencies))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("check", "http"), default="check")
    parser.add_argument("--requests", type=int, default=20000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--subjects", type=int, default=200)
    parser.add_argument("--ips", type=int, default=20)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    args = parser.parse_args()
    asyncio.run(run_check(args) if args.mode == "check" else run_http(args))


if __name__ == "__main__":
    main()
