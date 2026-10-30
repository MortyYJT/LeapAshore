## Context

TASKS.md P1 #3. Production runs one uvicorn process (anonymous mode) behind Caddy, with a Celery worker
and beat (P1 #2) on the same PostgreSQL 16. A turn runs in its own task (`advisor._detached`, P0 #5),
which settles the token reservation when it ends. The page keeps its conversation list in React state
only, so a conversation is reachable while its tab is open; a reload starts a new one.

## Decisions

- **D1 Thread = `{subject}:{conversation_id}`, unchanged.** The subject is `get_subject`'s (account in
  login mode, anonymous cookie otherwise), so a guessed conversation id reaches only the caller's own
  thread. Conversation ids are `[A-Za-z0-9_-]{1,40}`, so `{subject}:` is a prefix no other subject has;
  every per-subject SQL below matches on it (`starts_with`).
- **D2 Alembic creates the tables, not `setup()`.** CI and the production container already run
  `alembic upgrade head`; a second schema owner would be invisible to Alembic, and autogenerate would
  offer to drop tables it does not know. The revision is a copy of the library's `MIGRATIONS[0..9]` at
  3.2.0 (so it never changes when the library does), builds the three thread indexes without
  `CONCURRENTLY` (not allowed in Alembic's transaction; the tables are new and empty), and records
  versions 0..9 in `checkpoint_migrations`, which makes the library's `setup()` a no-op. The library is
  pinned; a test compares its migration list (count and digest) with what the revision applied, so an
  upgrade that adds a migration fails until a new add-only revision carries it. `alembic/env.py`
  excludes the four tables from autogenerate.
- **D3 Synchronous saver, async in a thread.** `AsyncPostgresSaver` binds to the event loop it was
  created on; the API's loop, the test client's per-request loops and the Celery worker are different
  loops. `PostgresSaver` over a `psycopg_pool.ConnectionPool` is loop-agnostic; its async methods are
  overridden to run the sync ones via `asyncio.to_thread`. The saver serialises its statements under its
  own lock, so the pool is `min 1, max CHECKPOINT_POOL_SIZE=2` (the second is a spare). The pool opens
  on first use (importing the API needs no database) and closes in the app's lifespan. Connection
  budget per API process: SQLAlchemy 5 + 10 overflow, checkpointer 2, plus one per confirm in flight
  (D5); PostgreSQL's default is 100.
- **D4 `durability="sync"`.** Each step's checkpoint is saved before the next step starts. After a
  confirmed write, the `tools` step is on disk before the model is called again, so a process that dies
  after the write leaves the thread past it, and a repeated confirm finds nothing to do. The write is
  also idempotent by construction (the tool recomputes the whole target portfolio from the current rows
  and replaces it), so the remaining window — death between the portfolio commit and the step's
  checkpoint — re-applies the same target rather than adding a second row.
- **D5 One confirm per thread at a time.** `/confirm` takes `pg_try_advisory_lock(key(thread))` on a
  connection of its own, re-reads the paused state under it, and holds it until its detached turn has
  ended (released in `_detached`'s `after`). A second confirm meanwhile is told 「这个操作正在处理，请稍候。」;
  one after it finds nothing pending. Session-level advisory lock rather than a Redis lock: a process
  that dies mid-turn releases it with its socket, so a crash never strands a change behind a TTL. The
  lock connection is closed, never pooled, so it cannot leak onto another request. The `confirm` event
  carries the interrupt's `id`; a confirm that sends `interruptId` resumes exactly that interrupt
  (`Command(resume={id: answer})`) and is refused when it is no longer the pending one, so a late
  repeat cannot approve a newer change. Without the id (a page loaded before this change) it behaves as
  before. Order in `/confirm`: pending? → lock → pending again? → admit (token caps) → run; the lock is
  released on every exit, including a 429/503 from admission. Chat turns take no lock (they are
  window-limited and write nothing that needs confirming).
- **D6 Prune after every turn.** LangGraph stores a new copy of the message list for every step, so a
  thread grows quadratically. When a turn ends (`_detached`'s `after`, after the reservation is
  settled), the thread is pruned with the library's `keep_latest`, which keeps the latest checkpoint
  with its pending writes — a paused change survives it (tested). Best effort: a failure is logged.
  History replay is not used anywhere.
- **D7 Retention follows the subject.** Deletion (`delete_subject`: account deletion and the 90-day
  anonymous sweep) deletes the subject's threads in the same transaction as its rows. A merge on first
  login moves the anonymous subject's threads to the account (rewriting `metadata.client_id`), except
  a conversation id the account already has, whose anonymous copy is dropped — the target wins, as for
  every other merged row. Independently, threads whose newest checkpoint `ts` is older than
  `ADVISOR_THREAD_RETENTION_DAYS` (90) are deleted by the daily beat task in **both** modes: in
  anonymous mode the subject sweep is off, and without this the tables would only grow; a thread idle
  for 90 days is unreachable from the page anyway. `python -m app.cleanup --conversations-only` runs
  it by hand.
- **D8 An unanswered tool call is closed for the model.** Writing a new message instead of answering a
  confirm starts a new turn and leaves the model's tool call without a reply in the thread; an
  OpenAI-style API refuses that history, and with persistence the thread would stay broken across
  restarts. `main_agent` shows the model a tool reply 「未执行：用户没有回应这个操作，接着发了新消息。」 for
  every call that has none. The stored thread is unchanged. Measured 10-30 against `deepseek-chat`: the
raw history is refused with 400 「An assistant message with 'tool_calls' must be followed by tool
messages…」; the closed one is answered.

## Not done

- Conversation list across page reloads (the page still keeps conversations in memory).
- A lock for chat turns on the same thread (two tabs sending at once can still fork a thread).
- History compaction beyond keep-latest (a single long conversation still stores its whole history).
