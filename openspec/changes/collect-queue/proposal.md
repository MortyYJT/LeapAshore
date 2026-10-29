## Why

Requirements are collected by hand-driven agents, one school at a time: nothing re-collects a page
when it changes, deadlines age (130 already past on 2026-10-30), and 154 of the 287 in-scope schools
have never been collected. TASKS.md P1 #2 asks for a queue that collects one page per task, politely
and resumably, re-collects on a schedule, and records which requirement changed.

## What Changes

- **New subsystem `app.collect.queue`** on Celery with the existing Redis as broker:
  - one task per page (snapshot → dedupe by hash → extract with the advisor's model → `verify`);
  - a per-host token bucket in Redis shared by every worker (one request per 2 s per host, the
    snapshot tool's interval), with robots.txt and recorded refusals honoured as before;
  - exponential backoff for transient failures; a 401/403/429 or a robots.txt refusal is recorded
    and never retried around;
  - a model-spend budget (CNY, from the reported token usage) checked before every model call;
  - discovery: from a school's official listing page, the model picks which links on it are taught
    master's program pages (it can only choose among links the page has);
  - beat: daily re-collection of pages not fetched for 30 days, under a daily spend cap; daily
    90-day anonymous-data cleanup when login mode is on.
- **Schema (Alembic, add only):** `collect_pages` (the durable queue state and last result per page)
  and `requirement_changes` (which requirement of which program changed, old and new value, both
  snapshots).
- **Requirement files stay the source of the catalogue.** The queue never writes `programs`; an
  `export` command merges its results into `api/data/requirements/<school>.json`, which is reviewed,
  committed and imported as before. Nothing writes `verified_at`.
- **Refusals expire after 30 days** (new entries carry a time); entries recorded before this change
  have no time and stay until removed by hand.
- **Compose:** `worker` and `beat` services locally and in production; production snapshots live in
  a named volume, and the database stores only a school key and a sha256, never a path.
- `_schools.json` grows to the 287 in-scope schools, with official listing URLs.

## Impact

- Code: `api/app/collect/{queue,ratelimit,changes,discover}.py`, `api/app/worker.py`,
  `api/app/collect/snapshot.py` (pluggable rate limiter, refusal expiry), `api/app/models/collect.py`,
  `api/app/config.py`, `api/pyproject.toml` (celery), `compose.yaml`, `deploy/compose.prod.yaml`,
  `deploy/.env.example`, `Makefile`.
- Migration adds two tables. Production: back up, migrate (api start), start worker and beat.
- Model money: the back-fill run is capped at 100 CNY; the production beat at a daily cap
  (`COLLECT_DAILY_BUDGET_CNY`, default 1).
