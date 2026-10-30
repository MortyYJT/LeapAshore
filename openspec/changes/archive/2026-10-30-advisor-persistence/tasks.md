## Progress checklist

Branch `claude/pg-checkpointer`.

- [x] 1.1 Alembic revision for the four checkpoint tables; autogenerate ignores them; pin test
- [x] 1.2 `Checkpointer` (sync saver, lazy pool, async via thread); graph uses it; `durability="sync"`
- [x] 1.3 Red/green: confirm after a restart writes once (new graph, same database, real endpoints)
- [x] 1.4 Red/green: SIGKILLed process, second process resumes, third finds nothing
- [x] 1.5 Red/green: two simultaneous confirms write once (fails with the lock disabled)
- [x] 1.6 Red/green: another subject cannot answer; a stale interrupt id is refused
- [x] 1.7 Deletion, merge and 90-day sweep cover threads; beat sweeps threads in anonymous mode
- [x] 1.8 Prune to the latest checkpoint after each turn; paused change survives it
- [x] 1.9 Unanswered tool calls closed for the model
- [x] 1.10 Review fix: one portfolio change per model reply (shared interrupt id); sweep test scoped
- [x] 2.1 Web: `confirm` id sent back; privacy page
- [x] 3.1 Deploy: backup, migrate, read-only checks, one real advisor turn (paused, survived `restart api`)
