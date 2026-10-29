## Context

TASKS.md P1 #2. Collection so far: an agent per school uses `app.collect.snapshot` (robots.txt, a
file-locked 2 s interval per host, 403/429 recorded) and writes `api/data/requirements/<school>.json`
by hand; `app.collect.extract` (PR #42) does the extraction with the advisor's model and `verify`.
Celery, Redis and the compose services were approved in TASKS.md. Owner authority for this item:
TASKS.md 2026-10-30 (choices are Claude's, recorded in note/decisions.md).

## Decisions

- **D1 The queue's state is a table; Celery only runs it.** `collect_pages` has one row per
  (school, page URL): program name, CRICOS code, whether to render, `state`
  (`pending` → `queued` → `done` | `unchanged` | `blocked` | `failed` | `deferred` | `needs_human`),
  attempts, last error, the last snapshot's sha256 and visible-text sha256, the last result (the
  program in requirement-file shape, with `check` and `status`), model name, cost, timestamps. A
  broker that loses messages loses nothing: `resume` re-enqueues every `pending`/`queued` row, and
  `acks_late` + `reject_on_worker_lost` re-deliver a task whose worker died. Re-enqueueing a row that
  is already done is a no-op unless asked to re-collect.
- **D2 One task per page** (`collect.page`, argument: the row id). Discovery (`collect.discover`,
  one per school) only creates rows and enqueues page tasks. Pages are enqueued interleaved across
  schools, so concurrent workers are spread over hosts instead of queueing on one.
- **D3 Per-host token bucket in Redis**, shared by every worker and process: capacity 1, one token
  per `MIN_INTERVAL` (2 s), keyed by host, one Lua script (atomic). A task that would wait up to 10 s
  sleeps; longer, it re-schedules itself with that countdown (not counted as a retry). robots.txt
  fetches take tokens from the same bucket. The command-line snapshot tool keeps its file lock;
  `snapshot()` takes the limiter as a parameter.
- **D4 Failures.** robots.txt refusal, a recorded refusal, or HTTP 401/403/429 → `blocked`, recorded
  in the school's `_blocked.json` and the host refusal list as before, **never retried**. Timeouts,
  connection errors, 5xx and model/transport errors → retried with exponential backoff (60 s base,
  doubling, capped at 1 h, jittered), at most 4 retries, then `failed`. A model answer malformed
  twice → `needs_human` (extract's rule).
- **D5 Refusals expire after 30 days.** A refusal now records when it happened; after 30 days the
  host may be asked again, with the same User-Agent. A refusal recorded before this change has no
  time and holds until removed by hand. The 13 in-scope schools with no programs are retried through
  the queue under these rules: a host refused by robots.txt is re-read (robots cache is one day); a
  host with a standing 403 is not asked.
- **D6 Dedupe by hash.** A fetched page whose HTML sha256 or normalised visible-text sha256 equals
  the row's last one is `unchanged`: no model call, no change rows. Prior state for a page the queue
  has not seen comes from its requirement file (`snapshot_sha256`, `fields`), so the first
  production re-collection of a committed page is compared against the file.
- **D7 What counts as a change.** Only values whose check passed are compared, field by field: for
  IELTS/TOEFL the numbers and the recommended flag, for the Chinese-degree requirement the two marks,
  for the academic requirement and prerequisites the normalised quote (the page's words, not the
  model's paraphrase), for deadlines the (label-independent) set of dates. Kinds: `added`, `removed`,
  `changed`. Removals are recorded only when the new extraction kept at least one value: a page that
  lost everything (a failed render, a challenge page) is `needs_human`, not a wave of removals.
  `requirement_changes` stores school, page URL, program name, field, kind, old and new value (JSON),
  both snapshot sha256s and the detection time. Nothing reviews or applies them automatically.
- **D8 The queue never writes the catalogue.** `python -m app.collect.queue export [--out DIR]`
  merges results into the requirement files (a page's program is replaced by URL; others are kept;
  `collector`, `collected_at` updated); the files are reviewed in git, committed, and imported with
  the existing importer. One path into `programs` keeps every catalogue value traceable to a
  committed file. In production the beat's findings land in `collect_pages` and
  `requirement_changes`; bringing them into the catalogue is an export in the container, a copy back
  to the repository, a commit and the usual import (`note/handoff.md`).
- **D9 Where snapshots live.** Locally `api/var/snapshots/` (not in git), unchanged. In production a
  named volume `snapshots` mounted at `/app/var/snapshots` in the worker. The database stores a
  school key and sha256s only; the `text_path` in a snapshot's metadata file is never stored.
  Rendered pages need Node and Chrome, which the production image does not have: a page marked
  `render` is skipped there (`deferred`, reason recorded) and re-collected locally.
- **D10 Budget.** Cost = reported tokens × DeepSeek prices (settings, CNY per million, peak price
  as the upper bound), added to a Redis counter per budget key and to the row. Before every model
  call the counter is checked; over the cap the row is `deferred` with no call. The back-fill uses
  key `backfill` with 100 CNY; the beat uses `daily:<Beijing date>` with `COLLECT_DAILY_BUDGET_CNY`
  (default 1). At most a few calls in flight can pass the cap (one per worker).
- **D11 Discovery.** `_schools.json` gives each school its official listing URLs (found with web
  search, used only to find URLs; every page is fetched with the snapshot tool). The discover task
  snapshots each listing (rendering when plain HTML has under five candidate links), collects the
  links on it to the school's own hosts, and asks the model — by function call, with numbered links —
  which are taught master's program pages. Only numbers from the list are accepted, so a URL can
  never be invented; the program name is the link's own text. At most 60 programs per school
  (the agents' brief used the same stop). Discovery costs count against the same budget.
- **D12 Beat.** Asia/Shanghai: `recollect_due` daily at 04:07 enqueues up to
  `COLLECT_RECOLLECT_PER_DAY` (200) pages not fetched for `COLLECT_RECOLLECT_DAYS` (30) days, oldest
  first; `cleanup` daily at 03:17 runs `app.cleanup` with `--apply` **only when `AUTH_ENABLED`** —
  in anonymous mode every user is anonymous and the 90-day rule was written for login mode
  (handoff step 6).
- **D13 Broker.** Redis database 1 (`CELERY_BROKER_URL`), so Celery's keys never share a keyspace
  with the advisor's counters in database 0. Worker concurrency 4 locally, 2 in production.

## Risks

- Discovery depends on the model reading a link list; a wrong pick costs one page fetch and one
  extraction, and a page that states nothing is `待人工`, never imported as a value.
- `text`, `label`, `recommended` are the model's paraphrase (unchanged from PR #42); change detection
  ignores them, so a changed paraphrase is not a change.
- A site that varies its visible text on every request (dates, counters) defeats D6 and costs one
  extraction per re-collection; the daily cap bounds it.
- The production snapshot volume grows with page churn; size is checked after the first re-collection.
