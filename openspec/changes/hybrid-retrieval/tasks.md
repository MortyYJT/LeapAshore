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
- [ ] 2.1 Held-out once per ranking on the final code (`vector`, `hybrid` wait for the key)
- [ ] 3.1 Deploy: backup, stop writers, dump, restore into `pgdata`, digests, migrate, read-only checks
- [ ] 4.1 Blocked on MortyYJT: `EMBED_API_KEY`; then backfill, held-out `vector` and `hybrid`, privacy page
