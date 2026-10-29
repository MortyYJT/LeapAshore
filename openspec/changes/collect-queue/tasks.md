## Progress checklist

Branch `claude/collect-queue` (Phase 1 PR), then `claude/collect-backfill` (Phase 2 data PR).
A successor resumes from the first unticked line.

### Phase 1: the queue (code)

- [ ] 1.1 Celery dependency; `app/worker.py`; broker settings; compose `worker` + `beat` (local, prod)
- [ ] 1.2 Migration: `collect_pages`, `requirement_changes`
- [ ] 1.3 Red/green: Redis token bucket spaces requests per host across processes
- [ ] 1.4 Red/green: `snapshot()` takes a limiter; refusals record a time and expire after 30 days; legacy entries hold
- [ ] 1.5 Red/green: page task — blocked not retried, transient retried with backoff, unchanged skips the model
- [ ] 1.6 Red/green: change detection (numbers, quotes, deadline dates; no removals when everything was lost)
- [ ] 1.7 Red/green: budget stops model calls (`deferred`)
- [ ] 1.8 Red/green: export merges by URL, keeps other programs, writes no `verified_at`
- [ ] 1.9 Red/green: discovery accepts only listed links, caps at 60, names from link text
- [ ] 1.10 Beat schedule: `recollect_due` (due pages, daily cap) and `cleanup` (only in login mode)
- [ ] 1.11 `make verify`; review; merge; deploy (backup, migrate, worker + beat up, read-only checks)

### Phase 2: the back-fill run (data)

- [ ] 2.1 `_schools.json` → 287 schools, official listing URLs for the uncollected ones
- [ ] 2.2 Discovery for the ~154 uncollected + 13 zero-program schools (budget key `backfill`, 100 CNY)
- [ ] 2.3 Page run; spend and progress recorded here after each batch
- [ ] 2.4 Export, verify, commit in batches
- [ ] 2.5 Import into production (handoff procedure); README / PRD numbers recomputed

### Run log (Phase 2)

(spend, schools done, pages done — appended as the run goes)
