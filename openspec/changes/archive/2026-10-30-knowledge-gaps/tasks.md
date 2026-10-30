## Progress checklist

Branch `claude/knowledge-gaps`.

- [x] 1.1 Alembic (add-only): `knowledge_gaps`, `knowledge_gap_reports`, `accounts.role`
- [x] 1.2 `app.services.knowledge_gaps`: key, hash, record (upsert), list/show, review (recollect/dismiss)
- [x] 1.3 Graph: record in `refuse`, `answer_passages` (nothing checkable, no error), missing schools
- [x] 1.4 Deletion, merge re-key, 90-day report sweep in the cleanup
- [x] 1.5 `require_admin`, `/api/admin/knowledge-gaps`, `python -m app.roles`, `python -m app.knowledge_gaps`
- [x] 1.6 Compose: API gets `CELERY_BROKER_URL`; `.env.example` gets `KNOWLEDGE_GAP_HASH_KEY`; privacy page
- [x] 2.1 `make verify`; review; deploy with backup; key generated on the server: PR #67, deployed
      2026-10-30; `KNOWLEDGE_GAP_HASH_KEY` is set in the server's `deploy/.env` (checked 2026-10-31)
