## Context

TASKS.md P0 #5. Production runs anonymous mode (`AUTH_ENABLED` unset), one uvicorn process behind
Caddy, with DeepSeek as the chat upstream.

## Decisions

- **D1 Identity.** The subject is what `get_subject` returns: the account's subject in login mode, the
  anonymous cookie's id otherwise. A visitor who drops the cookie gets a new subject, so the per-IP
  limits (window and daily tokens) and the site cap are what bound anonymous abuse. Both subject and IP
  are always checked; a request passes only if every key passes.
- **D2 Sliding-window log in a Redis sorted set**, one key per (scope, id, window). One Lua script
  evaluates the token caps and every window, and records the request in every window only when all
  pass, so a refused request does not extend its own penalty. Time is Redis `TIME` (one clock for all
  workers). Retry-After is when the oldest entry that keeps the window full expires.
- **D3 Defaults** (environment variables): subject `10/60,60/3600`, IP `30/60,200/3600` (requests per
  seconds); daily tokens per subject 200,000, per IP 600,000, site 2,000,000 (the site figure is
  TASKS.md's). An intent call averaged about 530 tokens in the PR #38 eval (58,184 tokens over 110
  calls); a full agent turn has not been measured, but with 1,500 output tokens per step and a system
  prompt plus evidence of a few thousand, 200,000 is still dozens of turns. The IP numbers leave room
  for a shared campus NAT.
- **D4 Token accounting after the fact.** A LangChain callback adds each finished call's
  `total_tokens` to the subject, IP and site day counters as the call ends. Caps are checked before a
  turn starts (`used >= cap` refuses), so a turn that starts under the cap may finish over it; the
  overshoot is bounded by one turn (`MAX_AGENT_STEPS + 1` calls, each output-capped by D5). A call cut
  off by a client disconnect before the model reports usage is not counted.
- **D5 `max_tokens`** 1,500 for agent replies and 200 for the intent router, passed in the request body
  as `max_tokens`. LangChain's `max_tokens` field is sent as `max_completion_tokens`, which DeepSeek
  ignored in a measured call (206 tokens back with a limit of 8); `extra_body` reaches the wire as is.
- **D6 Fail closed.** If Redis does not answer within 0.5 s the advisor returns 503 and spends nothing.
  The advisor is the only paid endpoint and the rest of the site does not touch Redis, so an outage
  costs the advisor alone; failing open would make the caps void exactly when nobody is watching.
  Recording usage after a call is best effort (logged), since the money is already spent.
- **D7 Confirm is not windowed, only capped.** `/confirm` resumes a turn the applicant already paid a
  window slot for and only runs when a change is pending, so it checks the token caps but not the
  windows; refusing it would strand the pending change.
- **D8 Client IP.** `TRUSTED_PROXIES` lists IPs, CIDRs or hostnames (resolved, cached 30 s). The
  right-most `X-Forwarded-For` entry is used only when the connection's peer matches; otherwise the
  peer address. Caddy's `reverse_proxy` already replaces a client's `X-Forwarded-For` when it has no
  `trusted_proxies` (measured on 2.11.4); the Caddyfile now sets it explicitly to `{remote_host}` so a
  future change to that default cannot reopen it. `TRUST_FORWARDED_FOR` is replaced by this setting.
- **D9 Day boundary** is midnight Beijing time (UTC+8, fixed offset, no DST): the users are in China.
  Day keys expire after two days.

## Risks

- One Redis for limits now and the Celery broker later: `noeviction` and a 256 MB cap, so a full Redis
  refuses writes (advisor 503) rather than silently dropping counters.
- Anonymous mode: a cookie-less attacker on many IPs is bounded only by the site cap.
