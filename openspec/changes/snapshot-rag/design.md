## Context

TASKS.md P1 #5. The collectors keep a snapshot of every official page they read (`<school>/<sha256>.txt`
visible text, `.html`, `.json` record) in `api/var/snapshots/` locally and, since P1 #2, in the
production worker's `snapshots` volume. The requirement files cite each program's page by
`snapshot_sha256` and shared pages by `source_sha256` + `source_url`. The advisor's requirement route
(P0 #4, P1 #4) answers from catalogue columns only; tuition, recommendation letters and interviews are
not columns. P1 #4 left a full-text + pgvector + RRF ranking whose vector half waits for a SiliconFlow
key (`EMBED_API_KEY`), which still does not exist (2026-10-30).

## Measurements (before designing storage, 2026-10-30)

Commands run in `api/`.

- Local snapshot store, everything: `du -sh var/snapshots` 3.0 GB (HTML included);
  `find var/snapshots -name '*.txt' -not -path '*/_*' | wc -l` 14,026 text files,
  `... -print0 | xargs -0 cat | wc -c` 255,153,959 bytes of text. Many are older versions of a page,
  listing pages and pages no file cites.
- Production `snapshots` volume (`docker compose exec worker ...` the same commands): **0 files**. The
  queue's beat has not run yet (first run 10-31 04:07); nothing was ever copied there.
- Pages the requirement files cite, at the snapshot each cites (`python -m app.collect.chunks measure`):
  **9,345 pages** of 250 schools, none missing; **176,354,596 characters**; per page median 13,693,
  p99 80,176, max 744,901 (a Paris 1 catalogue page). Of these, 8,849 are program pages and 552
  distinct shared pages (counted by an exploratory script before the command existed; the command
  de-duplicates by URL).
- Boilerplate (navigation, footer): removing lines that open or close at least half of a school's pages
  (at least 3 pages) leaves **139,748,877 characters** (-21%). Removing such lines anywhere in the page
  would leave 81 M (-54%) but would also remove a requirement every program page of a school states
  the same way ("Interview required"), so only the head and tail are trimmed (D2).
- Chunks at three sizes (lines packed, before the trim; exploratory script): 800 characters 249,930
  chunks, 1,200 characters 163,098, 2,000 characters 96,715. After the trim at 1,200: **132,208**.
- Local ingest (`python -m app.collect.chunks ingest`, 37 s): 9,413 pages (the 9,345 plus pages the local
  queue collected that no file cites yet), 254 universities, 7,362 pages linked to a program, 45 pages
  empty after the trim; **134,843 chunks, 142,527,096 characters**. Tables: `snapshot_chunks` 350 MB
  (190 MB heap, 160 MB indexes and TOAST; the GIN index 43 MB), `snapshot_pages` 8 MB. Production's
  whole database was 33 MB before this change. A second ingest writes nothing.
- Query cost: a two-school full-text search over the chunks (`EXPLAIN ANALYZE`) 0.9 ms through
  `ix_snapshot_pages_university_id` and `ix_snapshot_chunks_page_id`.
- Topic coverage of the cited program pages (regular expressions, exploratory): tuition 6,178 of 8,827
  pages (205 schools), recommendation letters 1,778 (130), interview 2,280 (181).

## Decisions

- **D1 Which pages.** The pages the committed requirement files cite, each at the snapshot its values
  were checked against: a program's own page (`snapshot_sha256`) and every shared page a value quotes
  (`source_sha256` with `source_url`; a shared quote without a URL cannot be cited and is skipped).
  Programs whose values did not pass (`待人工`) are included: their page still states fees and
  interviews. A page the collection queue holds as `done` or `unchanged` with a snapshot is taken at the
  queue's snapshot (it is newer), and a page it collected that no file cites yet is added. Older
  snapshots, listing pages and refused pages are not chunked.
- **D2 Boilerplate: head and tail only.** A line on at least half of a school's pages (and at least 3) is
  removed only while it opens or closes the page. Measured -21%. The trim also keeps navigation words
  ("Fees and scholarships" on every page) out of the topic search.
- **D3 Chunks: whole lines, at most 1,200 characters, no overlap.** The text is already one block per
  line; consecutive lines are packed, a line longer than 1,200 characters is cut after the last sentence
  end that fits, else the last space. 1,200 characters is about 300 English tokens, so six passages and
  the prompt stay near 2,500 input tokens (measured: 54,746 input tokens over 31 answer calls, 1,766 per
  call). Chunks are verbatim page text, so a quote is checked against exactly what is stored. The
  chunker's name (`lines-1200-trim50-v1`) is stored per page; a new chunker re-cuts every page.
- **D4 Schema, add-only (Alembic `f7c2d9a4e816`).** `snapshot_pages` (id = uuid5 of the URL, URL unique,
  school key, university FK cascade, program FK set null, title, snapshot sha256, fetched_at,
  content sha256 of the trimmed text, chunker, chunk count), `snapshot_chunks` (page FK cascade, ordinal,
  text, text sha256, generated `search_tsv = to_tsvector('english', text)` with GIN), and
  `snapshot_chunk_embeddings` (chunk FK cascade, model, content sha256, `vector(1024)`). **No path** is
  stored: the school key and sha256 name the snapshot, as in `collect_pages`. Universities are resolved
  from the cited program's row (Australian schools' are CRICOS rows), else the row named by the school
  key, else the one row with the school's English name from `_schools.json`.
- **D5 Idempotent ingestion and the queue hook.** A page is rewritten only when its trimmed-text sha256,
  snapshot, school, program, title, fetch date or chunker differ. When only the record differs (the
  same visible text at a new snapshot), only the page row is updated: the chunks, their ids and their
  vectors stay. When the text differs, its chunks are deleted and re-inserted in the school's
  transaction. `--prune` deletes pages the files no longer cite (off by default); a cited page whose
  snapshot is missing from the store is kept. The queue calls `refresh_page` after it commits a page as `done` or `unchanged` (a page that
  lost every value keeps its old chunks, as its old result); the boilerplate is learnt from the
  school's stored pages read at their stored snapshots. A failure there is logged and never fails the
  page; the next ingest catches up.
- **D6 Routing.** `data/advisor/page_topics.json` lists the topics (tuition, recommendation letters,
  interview) with the words applicants use and the phrases the chunks are searched for. A question goes
  to the passages when it names a topic and a school and the intent router said 官方要求核验 or 通用问答;
  planning, profile and task messages keep their routes, and a question that names no school keeps its
  old route (a general question is not turned into a refusal). Only the last message is read, as in the
  requirement gate.
- **D7 Retrieval.** The schools are recognised and narrowed by country exactly as the requirement gate
  does. A named subject restricts the pages to its programs' pages (same field and specific-subject
  pattern as the requirement gate) plus pages owned by no program (fees, admissions), so another
  programme's fee is never evidence for this one; no subject: every page of the school. Inside that
  scope: chunks matching the topic phrases (`phraseto_tsquery`, OR'd), ranked by `ts_rank_cd`; with a
  question vector, `vector` ranks by cosine distance and `hybrid` fuses both lists by RRF (k=60, as P1
  #4), falling back to full text without a vector. At most 2 chunks per page, schools take turns, 6
  passages. Every ranking reads only the chunks that state the topic: vectors reorder them, never add
  to them, so a school whose pages never mention the topic is refused whatever the ranking. No
  passage: refused with counts (school has no page / no page of that subject / no page
  states the topic).
- **D8 Generation: one function call, sent whole.** The model (the advisor's `CHAT_*`, temperature 0)
  returns `sentences[]`, each with `citations[]` of a passage number and a verbatim quote. The reply is
  shown only after the check, so nothing unchecked is streamed; the trade is that the answer arrives at
  once instead of token by token. An unreadable function call is an empty answer, so a refusal.
- **D9 The check.** For every sentence: at least one citation; each passage number exists; each quote is
  at least 12 characters and, after the collectors' folding (`collect.text.normalize`), a substring of
  the stored chunk; every number in the sentence (Arabic digits, thousands separators folded, and
  Chinese counts 二 to 十 before a measure word) is in that sentence's quotes, where English number
  words and month names count as their numbers (not "may", the modal verb, and not 一, which before a
  measure word is as often the article). One failing quote drops the whole sentence.
  Nothing left: a refusal that lists the pages read and states nothing. Shown answers end with the
  fetch dates and 待核验 (no human has verified a chunk; `verified_at` is untouched). The check is
  syntactic: a verbatim quote that does not support its sentence, or a sentence about another
  program, passes; that is the next item's faithfulness check.
- **D10 Vectors wait for the key.** `snapshot_chunk_embeddings` is created empty. `python -m
  app.agent.embeddings --chunks` fills it (dry run: 134,843 chunks, 142,527,096 characters, about 4,200
  requests of 32; price 0 for `BAAI/bge-m3`); the hourly beat does programs then chunks, at most 2,000
  of each a run, and nothing without a key. About 135,000 vectors of 1,024 floats are about 550 MB.
- **D11 Eval.** 38 questions (`evals/passage_questions.json`): 12 tuition, 10 recommendation, 10
  interview answerable ones whose gold page and sentence were found by regular expressions over the
  chunks, and 6 unanswerable ones (3 schools with no page, 3 whose pages never mention the topic).
  AI-labelled. One live run with DeepSeek, recorded; CI replays the recording through the check. The
  retrieval was looked at once before the live run (to catch broken school recognition); nothing was
  tuned on it.
- **D12 Production data.** Production's volume is empty, so the cited `.txt` files and their `.json`
  records (with the local `text_path` removed) are copied into it, and the ingest runs in the worker
  container. The same files give the queue's change detection there the baseline it has locally (a
  re-collected page whose visible text is unchanged costs no model call).

## Risks / Trade-offs

- Database size: about +360 MB in production (33 MB before); backups grow accordingly.
- The check cannot see a supported-looking but irrelevant quote or a misattributed program (D9).
- English full text only: pages in other languages are matched by the listed non-English phrases
  only, without their stemming.
- Mixed questions ("雅思和学费") go to the passages; the IELTS part is answered only if a passage
  states it.
