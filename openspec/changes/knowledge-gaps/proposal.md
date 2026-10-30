## Why

TASKS.md P2 #1. When the advisor cannot source an answer it refuses and tells the applicant "已记录为待采集"
— but nothing is recorded: the gate writes one log line (`knowledge gap reason=… query=…`) that nobody
reviews and that rotates away. The item asks for the refusals to be stored (the asker identified only
by a hash), a review interface, and, once a person has reviewed a gap, a re-collection task on the
collection queue (P1 #2).

## What Changes

- **Schema (Alembic, add-only)**: `knowledge_gaps` (one row per distinct gap: route, reason, schools,
  subject areas, page topics; counts and first/last seen; review status), `knowledge_gap_reports` (one
  row per refusal: the gap, a keyed hash of the subject, the question truncated to 500 characters, the
  time) and `accounts.role` (nullable; `admin` is the only value used).
- **Recording**: every advisor refusal — the requirement gate, the page-topic gate, an answer from the
  pages with nothing checkable left, and a requirement answer that had to leave out a named school — is
  recorded in the turn, best effort (a failure is logged, the turn is not affected). Refusals with the
  same key add to one gap. A refusal caused by the model being unavailable is not a gap and is not
  recorded (PR #65).
- **Review**: `GET /api/admin/knowledge-gaps`, `GET /api/admin/knowledge-gaps/{id}`,
  `POST /api/admin/knowledge-gaps/{id}/review` (`recollect` or `dismiss`), admin accounts only; the
  same operations as `python -m app.knowledge_gaps list|show|review` for the server shell, which works
  in anonymous mode too. `recollect` maps the gap's schools to collection keys, re-queues their pages
  that have not been collected successfully and sends a discovery task per school.
- **Privacy**: the subject is stored only as `HMAC-SHA256(KNOWLEDGE_GAP_HASH_KEY, subject id)`; never an
  account id, email or IP. Deleting a subject deletes its reports; merging an anonymous subject into an
  account re-keys its reports; reports are deleted after 90 days. Gap rows hold no personal data and
  are kept.

## Impact

- Code: `api/app/models/knowledge_gap.py`, `api/app/services/knowledge_gaps.py`,
  `api/app/routers/admin.py`, `api/app/knowledge_gaps.py` (CLI), `api/app/agent/graph.py`,
  `api/app/deps.py` (`require_admin`), `api/app/services/accounts.py`, `api/app/cleanup.py`,
  `api/app/worker.py`, `api/app/config.py`, `deploy/compose.prod.yaml`, `deploy/.env.example`,
  `web/app/privacy/page.tsx`.
- Ops: production needs `KNOWLEDGE_GAP_HASH_KEY` (a random secret, generated on the server, never
  committed) and the API container needs `CELERY_BROKER_URL` to send tasks.
- Not in scope: an admin page in the web app and the way MortyYJT's account gets its role in
  production (P2 #3 "人工核验入口"); login mode is still off in production, so the API is reachable only
  once it is on — the CLI covers review until then.
