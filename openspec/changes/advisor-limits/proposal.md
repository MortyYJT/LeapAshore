## Why

The advisor is the only endpoint that spends money: every turn calls the chat model one to seven times
(intent, then up to `MAX_AGENT_STEPS` agent steps). Nothing bounds how often a caller may ask or how
many tokens a day the site may spend, and the model calls carry no output limit. Production runs in
anonymous mode, where a new cookie is a new identity, so a per-identity limit alone is not a limit.

## What Changes

- **Redis** joins both compositions (`compose.yaml`, `deploy/compose.prod.yaml`); the P1 Celery queue
  reuses it. Client library: `redis` (redis-py, its asyncio client).
- **Sliding-window rate limits** on `POST /api/advisor/chat`, per subject (the account in login mode,
  the anonymous client id otherwise) and per client IP, checked together in one Lua script so a refused
  request consumes nothing.
- **Daily token caps** per subject, per IP and site-wide (default 2,000,000), counted from the model's
  reported usage and checked before each chat and confirm. Days run on Beijing time.
- Over a limit: **429** with `{"detail": {"code", "message", "retryAfter"}}` and `Retry-After`; the
  advisor page shows the Chinese message. Redis unreachable: **503**, fail closed.
- **`max_tokens`** on every model call, sent as `max_tokens` (DeepSeek ignores the
  `max_completion_tokens` field LangChain sends by default; measured).
- **Client IP** comes from `X-Forwarded-For` only when the connection's peer is a listed proxy
  (`TRUSTED_PROXIES`, production: the `caddy` service), and Caddy overwrites that header explicitly.
- All limits are environment variables.

## Impact

- Code: `api/app/limits.py` (new), `api/app/net.py` (new, client IP), `api/app/routers/advisor.py`,
  `api/app/agent/{llm,intent}.py`, `api/app/config.py`, `web/lib/advisor.ts`, `web/app/advisor/page.tsx`.
- Ops: a `redis` service and volume in both compositions; `deploy/Caddyfile` sets `X-Forwarded-For`.
- CI: the backend job gets a Redis service.
- No schema change.
