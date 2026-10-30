## Why

TASKS.md P1 #5. The advisor answers requirement questions only from the catalogue's structured columns
(English, marks, academic requirement, deadlines, prerequisites). Questions applicants ask just as often
— tuition, recommendation letters, whether there is an interview — are on the same official pages, in
the snapshots the collectors already took, but nothing the advisor can read holds them. The item asks
to measure the full snapshot text first, chunk it into the production database (no local paths), answer
those questions from the chunks, check every quote verbatim after generation (drop the sentence or
refuse), and report the citation verification pass rate.

## What Changes

- **Schema (Alembic, add-only)**: `snapshot_pages` (one row per official page: university, optional
  program, URL, title, snapshot sha256, fetched date, the sha256 of the text that was chunked),
  `snapshot_chunks` (the page's text in pieces, with a generated English full-text vector and a GIN
  index) and `snapshot_chunk_embeddings` (bge-m3 vectors, empty until the SiliconFlow key exists). No
  path is stored anywhere.
- **Ingestion** (`python -m app.collect.chunks ingest`): the pages the committed requirement files cite,
  at the snapshot each was checked against (or the collection queue's newer one), boilerplate head and
  tail lines removed per school, packed into chunks of at most 1,200 characters. Idempotent: a page
  whose chunked text has not changed is not rewritten. The collection queue refreshes a page's chunks
  when it re-collects the page.
- **Advisor route `passages`**: a question about tuition, recommendation letters or an interview that
  names a school (and that the intent router sends to requirements or general Q&A) is answered from the
  named schools' chunks: full-text ranking now, RRF with vectors when a question vector is available
  (the P1 #4 plumbing). The model returns sentences, each with the passage number and the exact words it
  relies on; every quote is checked against the stored chunk, a sentence with a failing quote (or a
  number its quotes do not contain) is removed, and when nothing sourced remains the advisor refuses.
- **Eval**: a labelled set of 38 questions grounded in actual snapshot text
  (`api/evals/passage_questions.json`); `python -m evals.run_passages` records a live run (passages,
  raw answers, tokens) and replays a recorded run without a database or model, which CI does.

## Impact

- Code: `api/app/collect/chunks.py`, `api/app/agent/{passages,answer,graph,embeddings}.py`,
  `api/app/models/snapshot.py`, `api/app/collect/queue.py` (hook), `api/app/worker.py`,
  `api/app/routers/advisor.py`, `api/data/advisor/page_topics.json`, `api/evals/run_passages.py`.
- Data: about 9,300 pages and 130,000 chunks; production database grows from about 33 MB by a few
  hundred MB (measured locally before deploying).
- Ops: the referenced snapshot texts are copied into production's `snapshots` volume (text and a
  metadata file without its local path), then ingested in the worker container. The same texts give
  the collection queue's change detection its baseline there.
- Privacy: nothing new leaves the server; the passages sent to the chat model are public page text.
