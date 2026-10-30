## Progress checklist

Branch `claude/collect-queue` (Phase 1 PR), then `claude/collect-backfill` (Phase 2 data PR).
A successor resumes from the first unticked line.

### Phase 1: the queue (code)

- [x] 1.1 Celery dependency; `app/worker.py`; broker settings; compose `worker` + `beat` (local, prod)
- [x] 1.2 Migration: `collect_pages`, `requirement_changes`
- [x] 1.3 Red/green: Redis token bucket spaces requests per host across processes
- [x] 1.4 Red/green: `snapshot()` takes a limiter; refusals record a time and expire after 30 days; legacy entries hold
- [x] 1.5 Red/green: page task — blocked not retried, transient retried with backoff, unchanged skips the model
- [x] 1.6 Red/green: change detection (numbers, quotes, deadline dates; no removals when everything was lost)
- [x] 1.7 Red/green: budget stops model calls (`deferred`)
- [x] 1.8 Red/green: export merges by URL, keeps other programs, writes no `verified_at`
- [x] 1.9 Red/green: discovery accepts only listed links, caps at 60, names from link text
- [x] 1.10 Beat schedule: `recollect_due` (due pages, daily cap) and `cleanup` (only in login mode)
- [x] 1.11 `make verify`; review; merge; deploy (backup, migrate, worker + beat up, read-only checks) — PR #50, deployed 10-30
- [x] 1.12 Review fixes (PR #50): export every result, robots no-answer retried, atomic snapshot writes, budget deferral not pushed a month
- [x] 1.13 Found in the run: non-ASCII URLs percent-encoded; thin pages deferred where there is no Chrome

### Phase 2: the back-fill run (data)

- [x] 2.1 `_schools.json` → 287 schools, official listing URLs for the uncollected ones
- [x] 2.2 Discovery for the ~154 uncollected + 13 zero-program schools (budget key `backfill`, 100 CNY)
- [x] 2.3 Page run; spend and progress recorded here after each batch
- [x] 2.4 Export, verify, commit in batches
- [x] 2.5 Import into production (handoff procedure); README / PRD numbers recomputed (after PR #52, 10-30)

### Run log (Phase 2)

Spend is the upper bound at DeepSeek's peak price; `python -m app.collect.queue status` (in `api/`) shows it.

- 10-30 discovery: 157 of the 167 uncollected / zero-program schools had a listing URL (subagents, web
  search only, no school site touched); first pass 116 schools → 3,706 program pages. A second pass over
  20 schools that had failed for transient reasons (render timeouts, cut-off responses) added McGill (59,
  coursecatalogue.mcgill.ca), Alberta (60, its Acalog calendar) and 3 pages elsewhere. A second URL search
  for the rest could not run: the session's web-search quota was used up.
- 10-30 page run (8, then 16 threads, about 1.5 h): 3,833 pages at 122 schools → 3,628 done (118
  schools), 94 blocked (UAB, ACU, Notre Dame Australia, UTP refused with 401/403 part-way), 111 failed
  (60 Charles Darwin pages are session-bound Oracle APEX links that answer 302; 31 EdUHK pages: its
  robots.txt never answered over TLS; 19 answer 404; 1 kept failing on a redirect). 289 pages were rendered in Chrome (thin plain HTML).
- Spend: **36.37 CNY** upper bound at DeepSeek's peak price (pages 34.49 + discovery ≈ 1.88), under the
  100 CNY cap, so the run was not cut short.
- Exported 10-30: 3,628 programs (2,262 machine-checked, 1,366 with no value that passed: their page
  states requirements elsewhere) into 115 new files and 3 existing ones (McGill, Alberta, UKM).
- The 13 zero-program schools: McGill, Alberta and UKM now have programs; the other 10 still refuse us
  (robots.txt answers 403: Macquarie, QUB, Durham, Cardiff, Delft, UCD, Melbourne; HTTP 403: Bath,
  Otago; KU Leuven's robots.txt does not answer) and were not asked around.
- Found in the run and fixed: non-ASCII URLs, thin pages without Chrome, and **Crawl-delay**: 82 cached
  robots.txt files ask for 5–120 s; the snapshot tool (agents and queue alike) had used 2 s. 13 hosts in
  this run were fetched faster than they ask (Alberta's Acalog and Virginia's records at 120 s requested,
  Surrey's catalogue and Lisbon at 10 s, …). Honoured from commit "honour robots.txt Crawl-delay" on.
- 10-30 review of PR #51 (fresh context, scripted checks over every file): TOEFL/IELTS scales, empty
  strings and zeros, `verified_at`, local paths, duplicate URLs and ids, off-domain URLs, quotes on
  every `ok` value: all clean; the importer ran on every file. Three real problems, fixed in PR #52:
  1. A thin page on a host with a Crawl-delay over 10 s looped forever (plain fetch, then RetryLater
     on the render, render never remembered). The render is now committed before rescheduling.
  2. Australian programs without a CRICOS code made a second university row (CQU, SCU, WSU, Torrens,
     Canberra, named from the school key) or duplicated catalogue courses (Victoria, Flinders). The
     importer now writes an Australian school's programs only onto CRICOS rows; 65 machine-checked
     ones without a known code are skipped (3 Curtin rows from an earlier import stay in the catalogue).
  3. Non-program pages and polluted names: listing pages (SCU `?page=2..6`, La Trobe, Groningen, SDU,
     VUB, UKM, KFUPM), CQU bachelor's / associate degrees / "Course Not Found", WSU research and
     closing-dates pages, a Canberra bachelor's; names carrying icon CSS (Flinders) or a card's text
     (Dalhousie, Loughborough, UAM, Twente, ...). New `app/collect/tidy.py`: the name is cut back to the
     page's own `<h1>` when the heading is part of a long link text; the rules drop non-master pages;
     discovery and the queue apply them from now on. `python -m app.collect.tidy --apply` changed only
     queue-collected programs: 23 files, 305 renamed, 68 dropped, 8 Flinders programs got their CRICOS
     code by exact name. A rename is not made when it would give two programs in one file the same name
     (Loughborough's London and Loughborough campuses), nor when what it cuts is short ("(Online)"). Files now: 248 with a file, 234 with programs, 8,783 programs, 7,376 machine-checked; queue
     3,560 programs at 114 schools (2,213 machine-checked). Local import: 「有要求」 7,310, deadlines
     4,722 / 2,728 programs / 119 schools (324 past), academic 6,806, `verified_at` 0.
- Local cleanup after the reviewer's import of the old files: `remove_schools --apply` for the five
  school-key duplicates, `importer --prune` for Avondale, Flinders, Victoria, Sunshine Coast and the 24
  tidied files. Production never imported the old files, so it needs a plain import (no `--prune`:
  that would delete the 3 Curtin rows).
- 10-30 review of PR #52 (fresh context): three more, fixed in the same PR. (1) `queue export` would
  have undone the tidy (the queue's rows keep the old link text, and dropped URLs would be appended
  again): export now applies `tidy_file` and matches a row to the tidied name. (2) The heading rule cut
  "(Online)" off a Flinders online MBA, which then took the campus course's CRICOS code: see the two
  limits above. (3) A render that waited for a Crawl-delay and then failed made the page fail; the
  plain fetch it already had now stands (the sha is kept in `last_error` while it waits). Also: a
  discovered page that is not a program is caught on every visit, not only the first, so it never
  costs a model call again. An empty file still makes its school's row (as before; the advisor's school
  names point at those rows, e.g. `university-of-melbourne`), so SCU, La Trobe and Canberra, whose
  files are now empty, get a row with no programs like Melbourne's.
- Re-review of that commit: the awaited-render fallback caught only `RuntimeError`, but a Chrome
  timeout is `subprocess.TimeoutExpired`; it now takes any failure of the awaited render. Kept on
  purpose: an empty Australian file still makes a school-key row (pre-existing; the web merges rows of
  one school by name, and eval t29 names `university-of-melbourne`).
- 10-30 production import (after PR #52): backup `~/db-backup-20261030-pre-backfill.sql.gz`; api, web,
  worker, beat rebuilt; snapshot metadata unpacked to `/app/var/importmeta` in the api container (not
  the worker's `snapshots` volume) and the importer run with that root by a one-off script, no
  `--prune`: 248 files, 0 failed, 2,110 added, 5,200 updated, 84 skipped without a CRICOS code. Temp
  files deleted. Production equals local: 9,606 programs, 7,314 machine-checked, 「有要求」 7,310,
  4,722 deadlines / 2,728 programs / 119 schools (324 past), academic 6,806, `verified_at` 0; user
  tables unchanged by md5. Beat has not run `recollect_due` yet (first run 10-31 04:07 Beijing);
  `collect_pages` and `requirement_changes` are empty in production.
- 10-30 round 2 for the 39 schools with no file (owner's instruction: Claude subagents, not the
  DeepSeek API; DeepSeek spend for this round 0). Brief: the README's "Brief for a collecting agent",
  at most 20 programs per school this round, Australian programs only with a CRICOS code. Skipped
  because their host refused us within 30 days (not retried): TU Berlin, UAB, ACU, HKMU, Tung Wah.
  Batches of three: (1) Leiden, Aalto, Basel (2) TU/e, UB, Geneva (3) TU Dresden, KSU, KAU (4) CEU,
  Minnesota, Milan (5) Deakin, Griffith, QUT (6) Newcastle, Swinburne, CDU (7) UM, Lingnan, CityU
  Macau (8) MPU, Macao Tourism, Kiang Wu (9) ECU, JCU, Murdoch (10) UNE, UTAS (11) Centennial,
  Gratia, Nang Yan, UOW College HK, Macau Millennium. A successor: a school whose file exists is done
  or partial (`complete`, `remaining_urls`).
- 10-30 round 2 result: 34 files (16 with programs), 252 programs, 235 machine-checked, every
  Australian one with its CRICOS code. With programs: Leiden 20, Basel 20, Milan 20 (apply.unimi.it;
  www 403), CEU 20 (its study guide host; www's robots.txt disallows "Leap", a bad-bot list entry our
  user agent matches), CDU 20 (stable course URLs), Minnesota 19 (school sub-sites; most hosts 403),
  Swinburne 19, ECU 19, TU Dresden 18, Murdoch 18, KSU 17, UNE 17 (handbook; www robots 403), CityU
  Macau 10, KAU 6, Barcelona 5, Kiang Wu 4. Refused or nothing to collect: TU/e, Geneva (CAPTCHA),
  Aalto (HTTP 406), Deakin, Griffith, QUT, Newcastle, JCU, UTAS, Lingnan (robots.txt 403), UM
  (robots.txt 503), MPU, Macao Tourism, CityU www (robots.txt TLS failure), five colleges with no
  master's of their own (Centennial, Gratia, Nang Yan, UOW College HK, Macau Millennium). All files
  `complete: false` where the 20-program cap stopped them. DeepSeek spend for round 2: 0 (total for
  this item stays 36.37 CNY). Files now: 282 with a file, 250 with programs, 9,035 programs, 7,611
  machine-checked. Local import: 「有要求」 7,545, deadlines 4,763 / 2,754 programs / 123 schools,
  academic 7,039, `verified_at` 0; advisor tune Recall@4 1.0, Precision@4 0.98.
- Review of PR #54 (fresh context, scripted checks over all 34 files + snapshot spot checks): one
  problem, fixed: Swinburne's 19 programs all cited a generic China page ("for example ... 60 per
  cent") that no program page links to; the field was removed (no mark was set, counts unchanged).
