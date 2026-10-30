## Why

The advisor keeps its conversations in LangGraph's `InMemorySaver`. A portfolio change waits for the
applicant's confirm inside that memory (`interrupt` in `propose_portfolio_change`), so any restart of
the API — every deploy — silently drops every waiting change: the applicant clicks 确认 and is told
there is nothing to confirm. TASKS.md P1 #3: switch to the Postgres checkpointer; a change waiting
for its confirm must survive a restart and then be written correctly and exactly once.

## What Changes

- **Postgres checkpointer**: `langgraph-checkpoint-postgres` 3.2.0 (pre-approved), the library's
  synchronous `PostgresSaver` over its own small `psycopg_pool` pool, with its async methods run in a
  worker thread. New module `api/app/agent/checkpoint.py`.
- **Schema by Alembic**: revision `c4e8a1d2f6b9` creates the library's four tables
  (`checkpoint_migrations`, `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) from a copy of its
  migrations and records them as applied. Add-only.
- **Exactly once**: a confirm takes a per-thread Postgres advisory lock for its whole turn and re-reads
  the paused state under it; the `confirm` event carries the interrupt's `id`, and a confirm that names
  an id answers that change only. Steps are saved synchronously (`durability="sync"`).
- **Threads stay small**: after each turn the thread is pruned to its latest checkpoint.
- **Conversations follow their subject**: deleting a subject deletes its threads in the same
  transaction; merging an anonymous subject into an account moves its threads (the account's own win);
  the daily 90-day sweep deletes threads untouched for 90 days, in anonymous mode too.
- **A change abandoned for a new message** no longer breaks the thread: the model is shown a tool reply
  for every unanswered tool call.
- Privacy page: conversations are stored, deleted after 90 idle days and with the account.

## Impact

- Code: `api/app/agent/{checkpoint,graph}.py`, `api/app/routers/advisor.py`,
  `api/app/services/{conversations,accounts}.py`, `api/app/{cleanup,worker,config,main}.py`,
  `api/alembic/env.py`, `web/lib/advisor.ts`, `web/app/advisor/page.tsx`, `web/app/privacy/page.tsx`.
- Schema: four new tables (Alembic `c4e8a1d2f6b9`). Production applies it on container start.
- Dependencies: `langgraph-checkpoint-postgres==3.2.0`, which brings `psycopg-pool`.
- Ops: no new service. Each API process holds at most `CHECKPOINT_POOL_SIZE` (2) extra connections, plus
  one short-lived connection per confirm in flight.
