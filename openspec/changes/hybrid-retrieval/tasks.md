## Progress checklist

Branch `claude/hybrid-retrieval`.

- [x] 1.1 Evidence for the image move: `amcheck` on a reused musl data directory (7/53 btree indexes out
      of order); dump/restore into a `C`-collation cluster (0/53, per-table digests identical)
- [x] 1.2 Local `compose.yaml`, CI and `deploy/compose.prod.yaml` on `pgvector/pgvector:pg16`, new volume
- [x] 1.3 Alembic `e3a9c5d17b42`: extension, `programs.search_tsv` + GIN, `program_embeddings`
- [x] 1.4 Countries and full-text terms in `catalog_match.parse`
- [x] 1.5 Rankings `rules|fts|vector|hybrid` (RRF) in `evidence.search_requirements`; gate embeds the
      question only for vector rankings, falls back to full text
- [x] 1.6 Embedding client, idempotent resumable backfill (`python -m app.agent.embeddings`), hourly beat
- [x] 1.7 Eval `--retrieval`; refuses vector rankings without a key and full coverage; h08 corrected
- [x] 1.8 Tune split: `rules` and `fts` both Recall@4 1.0 / Precision@4 0.98
- [x] 1.9 Review fix: a country only narrows a shared school name (it dropped 港大 beside "英国")
- [x] 2.1 Held-out once per available ranking on the final code (960ed1a); `vector`, `hybrid` wait for the key
- [ ] 3.1 Deploy: backup, stop writers, dump, restore into `pgdata`, digests, migrate, read-only checks
- [ ] 4.1 Blocked on MortyYJT: `EMBED_API_KEY`; then backfill, held-out `vector` and `hybrid`, privacy page

## Run log

- 2026-10-30, local: `pg_basebackup` copy of the Alpine data directory started under
  `pgvector/pgvector:pg16`: no warning; amcheck 7/53 btree indexes "item order invariant violated".
  `pg_dump -Fc` / `pg_restore` into a `C`-collation cluster: 0/53, 28 table digests identical. Local
  `compose.yaml` moved the same way (new volume `offerpilot-pgdata`).
- Embedding dry run (local, 9,748 programs): 455,121 characters, about 305 requests of 32. No key, so
  no tokens measured.
- Held-out (K=4, 21 requirement questions, h08 corrected first), each once:
  reference (main dfb8912) Recall@4 0.8958 / Precision@4 0.9375; `rules` (960ed1a) identical, same rows;
  `fts` 0.9583 / 0.9531 (h12 TESOL now first; h14 still 1/3: two statistics programs sit in another
  field, which a ranking cannot reach); `vector`, `hybrid` refused: no `EMBED_API_KEY`. False-pass 0,
  false-block 0 for all. Results in `api/evals/results/hybrid-heldout-*.json`.

The digest used before and after the move (row count and an order-independent md5 per table):

```sql
-- Row count and an order-independent digest of every table in public (md5s sorted as hex, so the
-- result does not depend on the database collation).
do $$ declare r record; c bigint; d text; begin
for r in select tablename from pg_tables where schemaname='public' order by tablename collate "C" loop
  execute format('select count(*), md5(coalesce(string_agg(h, '''' order by h collate "C"), '''')) from (select md5(t::text) h from %I t) x', r.tablename) into c, d;
  raise notice '% % %', r.tablename, c, d;
end loop; end $$;
```
