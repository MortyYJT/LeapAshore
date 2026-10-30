## Progress checklist

Branch `claude/snapshot-rag`.

- [x] 1.1 Measure: local store, production volume, cited pages, characters, trim, chunk counts (design.md)
- [x] 1.2 Alembic `f7c2d9a4e816`: `snapshot_pages`, `snapshot_chunks` (+ GIN), `snapshot_chunk_embeddings`
- [x] 1.3 `app.collect.chunks`: trim, chunker, `measure`, idempotent `ingest [--prune]`, `refresh_page`
- [x] 1.4 Queue hook after done / unchanged; failures logged, never fail the page
- [x] 1.5 `page_topics.json`, routing in `classify_intent`, `app.agent.passages` retrieval + gate
- [x] 1.6 `app.agent.answer`: function-call answer, quote and number check, reply, refusal
- [x] 1.7 Chunk embeddings: `embeddings --chunks`, beat after programs (no key: nothing)
- [x] 1.8 Eval set (38), `evals.run_passages --check | --live | --replay`, CI replay test
- [x] 2.1 Local ingest: 9,413 pages, 134,843 chunks, second run writes nothing
- [x] 2.2 Live run once (DeepSeek, 2026-10-30): results in `api/evals/results/passages-2026-10-30.json`
- [ ] 3.1 Deploy: backup, migrate, copy cited snapshot texts into `snapshots`, ingest in the worker,
      read-only checks, at most one real advisor turn
- [ ] 4.1 Blocked on MortyYJT: `EMBED_API_KEY`; then `embeddings --chunks` and a vector/hybrid run

## Run log

- 2026-10-30 local measurements: see design.md "Measurements".
- 2026-10-30 retrieval looked at once before the live run (no model): 31 of 38 pass the gate, gold page
  among the passages for 26 of 32 answerable. Nothing changed after it.
- 2026-10-30 live run (`CHAT_BASE_URL=https://api.deepseek.com CHAT_MODEL=deepseek-chat`, reported model
  `deepseek-flash`, ranking `fts` because no embedding key): citation pass rate 82/82 = 1.0; sentences
  kept 76/79 (3 dropped, all `number_not_in_quotes`: a year from another sentence of the page, an
  amount quoted for the previous sentence, "at least a year" written as 1 年); answerable answered 31/32
  (1 gate refusal: i10, the program's page is filed under another field); unanswerable refused 6/6;
  gold page retrieved 26/32, gold sentence retrieved 21/32 and cited 20/32. Four answered questions
  (t06, t11, r07, i04) only say the passages do not cover the asked program. Tokens: answers 54,746 in
  / 6,388 out (11,520 cached), intent 18,306 in / 2,052 out; 0.172 CNY at DeepSeek's peak price.
