## Why

TASKS.md P1 #4. The advisor's requirement retrieval (P0 #4, `openspec/changes/advisor-retrieval`)
finds the named schools and subject area in SQL and then orders the rows inside a school with a
hand-written regex per subject. Two held-out misses come from that ordering: a word the applicant
typed ("TESOL") is not used unless the subject file has a pattern for it, and a pattern that is too
broad ("teach") ties every row. The item asks for PostgreSQL full-text search plus pgvector, fused with
Reciprocal Rank Fusion (RRF), then filtered by school and country, with SiliconFlow's `BAAI/bge-m3`
embeddings, and a held-out report for full-text only, vector only and hybrid.

## What Changes

- **Database image** `postgres:16-alpine` -> `pgvector/pgvector:pg16` (pre-approved) locally, in CI and
  in production. Moved by dump and restore into a new volume initialised with `C` collation, not by
  reusing the old data directory (D1).
- **Schema (Alembic, add-only)**: extension `vector`; a generated `programs.search_tsv` (English
  full-text vector over the program's names) with a GIN index; a new table `program_embeddings`
  (program id, model, content hash, `vector(1024)`).
- **Retrieval**: the scope (named schools, an optional country, the subject area, the specific-subject
  gate, requirement data, citable source) is unchanged; the order inside it becomes a mode:
  `rules` (the P0 #4 order), `fts`, `vector`, `hybrid` (RRF of the two). Production runs `hybrid`,
  which degrades to `fts` when no query vector is available.
- **Country filter**: a country or region in the question keeps only the named schools there (it tells
  same-named schools apart); a question that names only a country is still refused.
- **Embeddings**: an OpenAI-compatible client for SiliconFlow `/v1/embeddings`; an idempotent,
  resumable backfill (`python -m app.agent.embeddings`) that embeds programs whose content hash or model
  changed; an hourly beat task runs the same backfill so imported programs get vectors.
- **Eval**: `python -m evals.run_advisor --retrieval rules|fts|vector|hybrid`; held-out label h08
  corrected to the database.

## Impact

- Code: `api/app/agent/{evidence,catalog_match,embeddings}.py`, `api/app/models/program.py`,
  `api/app/{config,worker}.py`, `api/evals/run_advisor.py`, `api/alembic/versions/*`,
  `api/data/advisor/countries.json`.
- Dependencies: `pgvector` (Python, pre-approved).
- Ops: one-time database move (backup, dump, restore, verify per-table digests, old volume kept for
  rollback). An `EMBED_API_KEY` in `deploy/.env` turns the vector half on; without it nothing is sent
  to SiliconFlow and retrieval runs on full text.
- Privacy: with the key set, the applicant's question text is sent to SiliconFlow to be embedded; the
  privacy page must say so when the key is turned on.
