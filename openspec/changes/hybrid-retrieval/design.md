## Context

TASKS.md P1 #4. The requirement retrieval of P0 #4 (`openspec/changes/advisor-retrieval`) recognises
the named schools and subject in Python, filters in SQL (schools, `Program.field`, the specific-subject
gate, requirement data, citable source) and orders each school's rows by a regex from
`data/advisor/subjects.json`. The tune split scores Recall@4 1.0 / Precision@4 0.98, the held-out split
0.889 / 0.933 (h12 TESOL ordering, h14 statistics rows filed under another field). Production runs
PostgreSQL 16 on `postgres:16-alpine`, about 9,700 programs. No SiliconFlow key exists in the shell,
`api/.env` or the server's `deploy/.env` (checked 2026-10-30, names only).

## Decisions

- **D1 Image move by dump and restore, not by reusing the data directory.** `pgvector/pgvector:pg16` is
  Debian (glibc); the old image is Alpine (musl). Both say `en_US.utf8`, but musl's `strcoll` is
  `strcmp`, glibc's is linguistic. Measured on a `pg_basebackup` copy of the local database started
  under `pgvector/pgvector:pg16` (2026-10-30): PostgreSQL started without any warning
  (`datcollversion` is empty under musl, so there is nothing to compare), and `amcheck`'s
  `bt_index_check` failed 7 of 53 btree indexes with "item order invariant violated", including
  `programs_pkey`, `universities_pkey` and `sources_url_key`. Reusing the volume would need a REINDEX
  and would still change every `ORDER BY` on text to linguistic order. Instead: a new volume initialised
  with `--lc-collate=C --lc-ctype=en_US.utf8` (code-point order, which is what musl gave; Unicode case
  mapping as before) and `pg_dump -Fc` / `pg_restore`. Measured locally: all 53 indexes pass `amcheck`,
  and an order-independent per-table digest (row count + md5 of the sorted row md5s, 28 tables) is
  identical before and after. The old volume is never written, so rollback is "point the service back
  at it". Same procedure locally (`compose.yaml`), in CI (fresh, same initdb args) and in production.
- **D2 Schema, add-only (Alembic `e3a9c5d17b42`).** `CREATE EXTENSION vector`; a stored generated column
  `programs.search_tsv` with a GIN index; a table `program_embeddings (program_id PK/FK cascade, model,
  content_sha256, embedding vector(1024), embedded_at)`. Vectors live in their own table, not on
  `programs`, so a model change or a re-embed never rewrites catalogue rows, and the model and hash are
  the backfill's bookkeeping. **No ANN (HNSW/IVFFlat) index**: every query is restricted to the named
  schools (at most a few hundred rows), where the planner already goes through
  `ix_programs_university_id` and an exact distance over those rows is both exact and fast; an
  approximate index with a school filter applied afterwards can return fewer than K rows. Add one if a
  path without a school filter ever ranks by vector.
- **D3 Full text: English configuration over the program's names.** `to_tsvector('english', name_en ||
  name when different)`. Names are English in this catalogue (`name` equals `name_en` for nearly every
  row); PostgreSQL has no Chinese parser in the image and none is added. The question side is built in
  Python (`catalog_match.parse(...).fts_terms`): a Latin subject word as typed ("TESOL"), a Chinese one
  through its subject's English `gloss` ("统计" -> "statistics"), plus the other Latin words of the
  question, minus generic requirement words ("MSc", "IELTS", "requirement") and English function words.
  Each term is one OR branch (`plainto_tsquery`, so "computer science" needs both words); the score is
  `ts_rank_cd(..., 1)` (divided by 1 + log length, so "Statistics MSc" beats a long name that also says
  statistics). No terms: the full-text list is empty.
- **D4 Embeddings: SiliconFlow `BAAI/bge-m3`, 1024 dimensions, over plain HTTP.** OpenAI-compatible
  `POST /v1/embeddings` with `httpx` (LangChain's `OpenAIEmbeddings` tokenises with tiktoken and sends
  token ids, which other providers reject). A program's text is its English name, its other name if
  different, and its study area; never the school (the school is a filter). Price: siliconflow.cn/pricing
  lists `BAAI/bge-m3` as 免费 (read 2026-10-30; `Pro/BAAI/bge-m3` ¥0.07 per million tokens), recorded
  in `EMBED_PRICE_CNY_PER_MTOK=0`. Local catalogue: 9,748 programs, 455,121 characters to embed (dry
  run); tokens are not measured (no key), estimated at roughly 150-200 thousand, about 305 requests of
  32. No local model (TASKS.md 不做), no other provider.
- **D5 Backfill idempotent and resumable; the beat keeps it current.** `stale_programs` lists programs
  whose row is missing or whose model or text hash differs, in id order; each batch is embedded and
  upserted in its own transaction. A service error stops the run with what was stored kept; the next
  run continues. A program deleted meanwhile skips its batch. The collection queue never writes the
  catalogue (the importer does, by hand), so instead of a hook in one writer, a beat task
  (`maintenance.embed_programs`, hourly at :37, at most 2,000 programs a run) covers the importer, the
  seed and any other path. Without `EMBED_API_KEY` it does nothing. The question is embedded at request
  time with a 3 s timeout; on failure the gate logs it and ranks by full text (the advisor keeps
  answering; a refusal would be worse than a slightly worse order).
- **D6 Country is a filter on the named schools.** Words for a country or region
  (`data/advisor/countries.json`, keyed by `universities.country`) are matched after school names are
  blanked (香港 in 香港大学 is the school). A country only chooses among the schools that share one
  name ("英国的纽卡斯尔大学" keeps the UK one); a school named without ambiguity is kept whatever country
  is mentioned (review found the first version dropping 港大 from "我在英国读本科，问港大和 UCL"), and a
  shared name with no school in a named country keeps all of them. Countries are not bound to a
  position: "英国的纽卡斯尔和澳洲的悉尼" names two countries, so the shared name keeps both Newcastles. A question that names only a country is still refused as `no_school`: the gate's first
  condition is a named school (P0 #4), and answering "英国的计算机硕士" from four arbitrary schools is a
  product change, not a ranking one; it also would turn "澳门大学" (not collected) into answers from
  other Macau schools.
- **D7 Four rankings, one scope.** `rules` (P0 #4's order, kept for reference), `fts`, `vector`,
  `hybrid`. The scope and the gate are identical for all four, so the comparison measures ordering
  only. Within each school, each list is ranked with `rank()` over the usable rows; a row's RRF score is
  the sum of `1/(60 + rank)` over the lists it appears in (Cormack et al. 2009, k=60, not tuned); ties
  fall back to machine-checked first, then name. `ADVISOR_RETRIEVAL` (default `hybrid`) picks the
  production ranking; `hybrid` or `vector` without a question vector run as `fts` and say so in the
  trace (`gate_signals.ranking`). The eval refuses to score `vector`/`hybrid` unless the key is set and
  every program has a vector for the configured model.
- **D8 Eval.** `--retrieval` on `evals.run_advisor`. Held-out label h08 corrected before any held-out
  run (database truth since PR #48: five USYD architecture programs carry verified academic
  requirements; `answerable` false -> true, nothing else). Tuning only on the tune split. The held-out
  split is scored once per ranking, on the final code.

## Risks

- **The tune split cannot separate the rankings much.** Its relevance labels are field-level, and both
  `rules` and `fts` score Recall@4 1.0 / Precision@4 0.98 on it; the two differ in which relevant rows
  come first, which the metric does not see.
- **Vector half unmeasured.** Without a key, `vector` and `hybrid` are tested with planted and hashed
  vectors only; their held-out numbers wait for the key (blocked on MortyYJT).
- **Partial coverage during a backfill** biases `hybrid` towards rows that already have a vector.
  Minutes for the first fill; the beat closes gaps within the hour.
- **Privacy**: with the key on, question text goes to SiliconFlow. The privacy page must say so when the
  key is turned on (handoff step).
- **Image move**: writes between the final dump and the restore would be lost, so the API, worker and
  beat are stopped first. Rollback after accepting writes on the new volume loses those writes.
