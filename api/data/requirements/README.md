# Admission requirements collected from official program pages

One JSON file per school, `<school_key>.json`, for the taught master's programs of the schools in the
library's scope (29 countries and regions, see `docs/product/PRD.md` D5). `_schools.json` lists the schools in collection order
(`wave` 1 = Australia, 2 = Hong Kong, 3 = Singapore, 4 = UK, 5 = US, …).

Every value here was copied from an official page **with a verbatim quote**, and `verify.py` checked
the quote against a stored snapshot of that page. `status` is `机器核对` (machine-checked) only when
every reported value passed; otherwise `待人工` (human queue). Nobody has verified these by hand:
nothing here is `已核验`, and no file carries `verified_at`.

Snapshots (raw HTML + text) live in `api/var/snapshots/<school_key>/<sha256>.*`, which is not
committed. Each program cites its snapshot by sha256, so the exact page version is identifiable.

## Application materials

A program may carry a `materials` block beside its `fields`: what the page asks an applicant to send
(PRD-multi-device 3.7). It is written by a separate pass over the stored snapshots, with
`python -m app.collect.material_extract` (see "Brief for a material-extracting agent" below), and
checked by `verify` like every other value:

```json
"materials": {
  "snapshot_sha256": "f97dbf6c…",
  "extractor": "claude-subagent",
  "extracted_at": "2026-11-21",
  "rejected": 1,
  "items": [
    {"type": "recommendation", "count": 2, "note": "at least one academic referee",
     "quote": "…verbatim…", "check": "ok"},
    {"type": "other", "note": "course descriptions for core courses", "quote": "…",
     "source_sha256": "…", "source_url": "https://…", "check": "ok"}
  ]
}
```

- `type` is one of `cv`, `personal_statement`, `recommendation`, `transcript`, `language_score`,
  `test_score`, `portfolio`, `writing_sample`, `other`.
- An entry passes when its `quote` is verbatim in the snapshot it cites (`source_sha256`, else the
  block's) and is a sentence (10 characters or more), a `count` is written in the quote as a number
  standing on its own (not the 1 of `1,000`, the 2 of `2nd`, the 4 of `A4`) or as an English number
  word, and every number written in `note`, digits or words, is in the quote too. An `other` entry
  needs a `note` that names it. A failing entry is refused whole, with the reason; nothing is ever
  edited to make it pass.
- **No block** means nobody has read the page for materials. **A block with no items and
  `rejected` 0** means the page was read and lists none. A block left with refusals only, or
  withdrawn (`"withdrawn": "<why>"`, written by the `withdraw` command), says "not extracted": the
  importer removes what an earlier import wrote for the program. The catalogue keeps "not read" and
  "read, lists none" apart (`programs.materials_snapshot_sha256` is NULL until a page was read).
- The quote check is a substring check. It cannot tell "references are required" from the same words
  in "no references are required", nor whose count a number is; only a labelled set can measure
  that. There are two, both labelled by a model and not by a person: 11 chosen programs
  (`api/evals/materials_gold.json`) and 30 drawn at random (`api/evals/materials_gold_sample.json`);
  what they do and do not show is in `docs/measurements.md`.
- `note` is the extractor's summary and is not judged by a model yet: the summary check below does
  not cover materials.
- The block cites the snapshot it was read from. When the queue later collects the page again, the
  program's `snapshot_sha256` moves and the block keeps its own; `export` carries the block over.
- Import: `python -m app.collect.importer --materials-only <file>…` writes only the materials of
  programs the catalogue already holds, and nothing else; a full import writes them too. Either
  way a rerun over the same file writes nothing.

## Extracting with the model

`python -m app.collect.extract <school_key> <sha256> [--name "…"]` (run from `api/`) does step 3 below
with the advisor's chat model (`CHAT_*` settings) instead of an agent: it sends the snapshot's text,
gets the fields back through a function call, runs `verify` on them, drops every value that fails and
lists it in `rejected` with the reason. It prints one program in the format below plus `rejected`,
`unused` (academic routes after the first), `model` (the name the API reports) and token `usage`; it
does not write any file. `python -m evals.extract_rejection` measures it on ten collected schools
(results in `api/evals/results/extract-<date>.json`). A value it keeps has a verbatim quote, which is
not the same as a faithful summary, so it then runs the summary check below on every kept value.

## The summary check

`verify` cannot tell whether the words around a quote are faithful (UT Austin's MSCS: "Bachelor's
degree or comparable foreign degree; GPA of 3.0…" over a quote that only states the GPA).
`app.collect.faithful` asks the advisor's chat model, one request per program, whether each value's
quote on its own states its summary (`text`, `label`, `recommended`, which number is which). The
verdict is stored on the item:

- `summary_check`: `"ok"`, `"unsupported: <what the quote does not back>"`, or `"not checked: …"`
  (the model gave no usable verdict; it blocks like an unsupported one and a rerun tries again);
- `summary_sha`: a digest of the values judged. Editing the summary or the quote makes the verdict
  stale: it no longer counts, and `verify --write` removes it.

A value whose current verdict is not `"ok"` is **downgraded, not deleted or edited**: it stays in the
file with its reason, the importer does not write it, and its program is `待人工`. A value never
judged (collected by an agent, or before the check existed) counts as before. Backfill or re-judge:
`python -m app.collect.faithful` (estimate only) and `--apply [--budget-cny N]` (writes the files).
Measured against AI labels in `api/evals/faithfulness.py` (`python -m evals.faithfulness --replay
api/evals/results/faithfulness-2026-10-30.json`).

## The collection queue

`app.collect.queue` (openspec/changes/archive/2026-10-30-collect-queue) collects pages without an agent: Celery workers
(`make worker`, with Redis and the database up) take one page per task, wait their turn per host in a
Redis token bucket (one request per host every 2 s across all workers), honour robots.txt and recorded
refusals, skip the model when the HTML or visible text has not changed, extract with the advisor's model
and `verify`, and record every requirement that changed in `requirement_changes`. Model spend is
checked against a budget before every call.

```
python -m app.collect.queue discover <school_key>...   # listing (from _schools.json) → program pages
python -m app.collect.queue enqueue --budget backfill --cap 100
python -m app.collect.queue resume                       # after a restart: re-send pending/queued pages
python -m app.collect.queue status
python -m app.collect.queue export [--school K]          # merge results into these files (review, commit)
```

The queue never writes the catalogue: `export` writes these files, and the importer reads them as before.
A program the queue wrote carries `collector: "leapashore-queue (<model>)"` and its `fetched_at`.

## Brief for a collecting agent

You collect one school. Work from the repository root.
Use `api/.venv/bin/python` for the tools.

### Rules (not negotiable)

1. **Official pages only.** The school's own domain (and its official sub-sites, e.g. a graduate
   school). Never aggregators, rankings sites, agents, forums, or 指南者.
2. **Fetch every page you quote with the snapshot tool**, never with WebFetch or curl:
   `api/.venv/bin/python -m app.collect.snapshot <url> --school <school_key>`
   Add `--render` when the text file is near-empty or lacks the requirements (pages built by
   JavaScript). `--render` keeps our honest User-Agent; if the rendered page still shows a
   challenge, a CAPTCHA, or "access denied", that host is blocking us: record it and stop. Never
   solve a challenge or change identity to get past one. The tool prints JSON with `sha256` and `text_path`. It honours robots.txt and spaces
   requests out; do not try to make it faster.
   WebSearch / WebFetch may be used **only to find URLs**, never as the source of a quote, and never
   on a host of the school itself. Never run curl or wget against the school, robots.txt included:
   they do not carry our User-Agent.
3. **If the tool prints `{"blocked": …}` for HTTP 401/403/429, stop fetching that host.** Do not
   retry with other URLs on the same host to get around it, and never change the User-Agent.
   A **robots.txt** block covers the paths that robots.txt disallows: skip them, and fetch other
   paths on that host only if the tool lets them through (it checks each URL; `Disallow: /` closes
   the whole host).
   `www.x` and `x` are one host: a refusal from either holds for both (the tool enforces this).
   A *different official host* of the same school that publishes the same information as its own
   service (e.g. a handbook or a graduate-school site such as `handbook.monash.edu`) may be used —
   the snapshot tool checks that host's own robots.txt. Mirrors, caches, archives, and translation
   proxies may not. If every official host blocks you, record what you did in the file and finish.
4. **Never infer a value.** Every value needs a `quote` copied character for character from the
   snapshot's text file (copy from `text_path`, not from memory). If the page does not state it, leave
   the field out. A number you would have to calculate, convert, or assume is left out.
5. **Numbers must appear inside their own quote** (e.g. `"overall": 6.5` needs "6.5" in the quote).
6. Only **taught / coursework master's** (MSc, MA, MEng, MBA, Master of X by coursework, LLM, MPH…).
   Skip research degrees (MPhil, MRes, MSc by research), PhDs, graduate certificates/diplomas,
   and programs closed to international students.
7. Do not edit any other file in the repository, do not commit, do not install anything. Keep your
   own working files (scripts, notes, lists) in `api/var/work/<school_key>/`, which is not committed;
   never in the repository root or the shared scratch space (other agents run at the same time).
   Never stop processes by name (`pkill -f …`): that kills other collectors' fetches too. Stop only
   a process you started, by its pid.

### How to work

1. Find the school's official list of taught postgraduate programs (course finder, A–Z list,
   graduate school catalogue). Snapshot the listing page(s) and pull program links from the saved
   HTML (`grep -o 'href="[^"]*"' <sha>.html | sort -u`). For Australian schools, `_schools.json`
   gives `cricos_institution`: the courses of that institution in
   `web/prototype-fixtures/cricos-au-masters.json` are your checklist; record each one's `cricos_code`.
2. Look for the school's **official country-specific requirements for China** (e.g. "entry
   requirements by country: China", "international equivalences"). If it exists, snapshot it once and
   cite it from each program's `china_requirement` with `source_sha256`.
3. For each program, snapshot its page, then **do not read the whole text file**. Search it:
   `grep -n -i -E 'ielts|toefl|pte|average|gpa|wam|grade|class|honours|degree|equivalent|china|prerequisite|deadline|closing|apply by' <text_path>`
   and read only the matching lines (use `sed -n 'A,Bp'` for a little context). Copy quotes from there.
4. Write the file incrementally: after every ~10 programs, save `api/data/requirements/<school_key>.json`,
   so nothing is lost if you stop. Then run
   `api/.venv/bin/python -m app.collect.verify api/data/requirements/<school_key>.json --write`.
   For each failing field, re-copy the exact text from the snapshot or **delete the field**
   (`verify.py --drop-failing --write` removes every failing value at once). Never change a value to
   make it pass.
5. Stop after about **60 programs** or when your context is getting long, whichever comes first.
   Set `"complete": false` and list the program URLs you did not reach in `"remaining_urls"`, so the
   next run can continue. Set `"complete": true` only when the list is done.

### File format

```json
{
  "school_key": "university-of-sydney",
  "school_name_en": "The University of Sydney",
  "country": "Australia",
  "collector": "claude-code-subagent",
  "collected_at": "2026-10-29",
  "listing_urls": ["https://…"],
  "china_page": {"url": "https://…", "sha256": "…"},
  "blocked": [{"url": "https://…", "reason": "HTTP 403"}],
  "complete": false,
  "remaining_urls": ["https://…"],
  "notes": "one or two sentences: what was hard, what was skipped and why",
  "programs": [
    {
      "name": "Master of Computer Science",
      "url": "https://www.sydney.edu.au/courses/courses/pc/master-of-computer-science.html",
      "cricos_code": "111671D",
      "snapshot_sha256": "f97dbf6c…",
      "fields": {
        "academic": {"text": "Australian bachelor's in any discipline with a credit average (65%)", "quote": "an Australian bachelor’s degree in any discipline with a credit average (65 percent), or an equivalent qualification"},
        "china_requirement": {"min_mark_211": 80, "min_mark_other": 85, "quote": "…", "source_sha256": "…"},
        "ielts": {"overall": 6.5, "min_band": 6.0, "quote": "…"},
        "toefl": {"overall": 85, "min_band": 17, "quote": "…"},
        "prerequisites": [{"text": "programming", "quote": "…"}],
        "deadlines": [{"label": "Semester 1, 2027", "date": "2026-11-30", "quote": "…"}]
      }
    }
  ]
}
```

- Every field is optional; include only what the page states. `fields: {}` is allowed (the page
  states nothing usable) and sends the program to the human queue.
- `china_requirement.min_mark_211` = the minimum average (percent) stated for graduates of 985/211
  (or "Double First-Class" / top-tier lists); `min_mark_other` = for other Chinese universities. Fill a
  number only when the official page states it as a percentage for Chinese degrees; otherwise give
  only `text` + `quote`.
- `deadlines` are application closing dates for the next intake, as ISO dates. The quote must state
  the day, the month **and the year**; a year read off another part of the page ("31 May of the
  previous year", or the start year in a heading such as "for studies starting August 2027") is
  an inference: leave that deadline out. Numeric dates are read in the school's own
  order: month first for the US (`12/01/2026` = 1 December 2026), day first everywhere else, and in
  Canada, which uses both, only a date that reads one way (`15/01/2027`) counts. Month names are
  recognised in English, French, German, Spanish, Italian, Dutch, Portuguese, Swedish, Danish,
  Norwegian and Finnish, and 3月 / 3월 in Japanese, Chinese and Korean; set
  `country` exactly as `_schools.json` gives it.
- Run `verify.py --write` last; it adds `check`, `status`, and `verification`. Agents do not write
  `summary_check` / `summary_sha`; `python -m app.collect.faithful --apply <file>` adds them.

### Combining two official pages

Some requirements live on a shared page rather than the programme page: a graduate school's general
requirements, a faculty's English table, a "requirements by country: China" page. Use one only when
the **programme page itself names it** (its faculty, its English level, its required degree class),
and cite it with `source_sha256`. Typical cases:

- **UK**: a country page gives the percentage a Chinese degree needs for each UK class ("2:1: 80%
  from a 211 university, 85% from others"). When the programme's academic quote states its class,
  fill `china_requirement` with that class's percentages; its quote must contain both the class and
  the percentages. If the page groups universities by named lists other than 985/211 (or Double
  First-Class), give `text` + `quote` only, without `min_mark_*`.
- **English levels** ("Standard", "Higher", "Band B") defined on a separate page: cite that page's
  scores only for programmes whose page names the level.
- A **conversion table** (GPA scale ↔ percentage) is not a requirement: never turn it into a number.
- **US**: master's programmes live on department or professional-school sites, and the graduate
  school publishes the university-wide minimums (TOEFL/IELTS, "a bachelor's degree or equivalent").
  Use the graduate-school figure only for programmes whose page refers to it. A GPA expressed on a
  US 4.0 scale is not a Chinese percentage: quote it in `academic`, never in `min_mark_*`. Skip
  research-only master's (MS thesis track if listed separately as research), certificates, and
  programmes not open to international students.
- **Recommended is not minimum**: when the page only recommends, prefers or suggests a score ("we
  recommend at least", "preferred score", "Minimum Suggested Scores", "no minimum, but…"), still give
  `overall`, and add `"recommended": true`. A table that states both a preferred and a minimum score
  gives the minimum, without the flag. Averages of admitted students are neither: leave them out.
  A score that only exempts an admitted student from an in-house English exam or course is not an
  admission requirement either: give it as `text` + `quote`, without `overall`.
- **TOEFL on two scales**: since January 2026 some schools state the TOEFL minimum both on the
  0-120 scale and on the new 1-6 band scale. Put the 0-120 value in `overall`, keep both in the
  quote, and add `"scale_note": "TOEFL stated on 0-120 and 1-6 scales"`. A 1-6 value alone is
  given as `text` + `quote` without `overall`.

### Schools outside the English-speaking countries

- **Which degrees count.** In Japan, Korea, continental Europe and Latin America the master's degree
  (修士課程, 석사, Master, Laurea Magistrale, Mestrado…) is the normal postgraduate degree even when it
  ends in a thesis: include it. Skip only programmes labelled research-only or doctoral, and
  programmes with no intake from abroad. Prefer English-taught programmes and those that state an
  international admission route; collect local-language programmes only after those.
- **Which pages.** Use the school's own English pages where it publishes them; otherwise the
  local-language page. Quote it verbatim in its own language and write `text` in English.
- **Language requirements other than English** (German C1, TestDaF, JLPT N1, TOPIK 4, DELF B2…) go
  into `prerequisites` as `{"text": …, "quote": …}`. Never translate them into an IELTS score.
- **Entrance examinations** (Japan's 入学試験, Korea's 면접) and application windows: record a
  deadline only when the quote states its day, month and year.
- **Grade scales** (German 2.5, Dutch 7/10, Korean 3.0/4.5) stay in `academic` text. Only a
  percentage stated for Chinese degrees goes into `min_mark_*`.
- **Central portals** (uni-assist, Studyinfo.fi, Universityadmissions.se, Campus France) are
  official only for the procedure they run; a programme's own requirement comes from the school.

### What to report when you finish

One line of JSON: `{"school_key": …, "programs": N, "machine_checked": N, "human_queue": N,
"complete": true|false, "blocked": true|false, "note": "…"}`.

## Brief for a material-extracting agent

You read stored pages and say which application materials each one asks for. You do not fetch
anything and you do not call a model: you are the reader. Work from `api/`, with
`.venv/bin/python`. One run is about 30 programs; stop earlier if your context is getting long.

### Rules (not negotiable)

1. **Only what the page says.** Every entry needs a `quote` copied character for character from the
   text the `text` command prints: the whole sentence that asks for the material, so that it reads
   the same out of context ("No portfolio is required" must not be cut down to "portfolio is
   required"). Nothing from memory, from another school's page, or from what
   programs of this kind usually ask for.
2. **Unknown stays unknown.** If the page does not ask for a material, there is no entry for it. If
   the page lists no material at all, hand in `"materials": []`: that records "read, lists none".
   If you cannot tell (the text is an error page, a cookie wall, another program), hand in nothing
   for that program and say so in your report.
3. **Materials are things an applicant sends.** A CV, a statement, letters, transcripts, score
   reports, a portfolio, a writing sample, other documents. Entry requirements are not materials:
   a degree class, a GPA, a minimum IELTS score, prerequisite courses, work experience and deadlines
   are already in `fields`; leave them out. "IELTS 6.5 overall" is an eligibility rule; "upload your
   English test certificate" is a `language_score` material.
4. **`count` only when the page states a number** for this program ("two references", "3 letters").
   "A CV" has no count. A number for another track or another degree is not this program's, and a
   number that measures something else (a word limit, a page size) is not a count.
5. **`note` says what is particular** about the requirement, in English, in a few words (a word
   limit, who may write the letter, a set question, "optional"). No figure in it that is not in the
   quote. Leave it out when there is nothing particular. An `other` entry must have one: it is the
   material's name.
6. **One page.** Read the snapshot `targets` lists for the program. Only when that page itself links
   to a page that states this program's documents (and says so) may you use the linked page: fetch
   it with `python -m app.collect.snapshot <url> --school <school_key>` (it honours robots.txt and
   spaces requests out; a `{"blocked": …}` answer ends it, see rule 3 of the collecting brief), and
   cite it on the entry with `"source_sha256"`. Never use WebFetch, curl or a search engine for a
   quote.
7. Do not edit a requirement file by hand, do not commit, do not touch any other file. Keep your
   working files in `api/var/work/materials/`.

### Types

`cv`, `personal_statement` (statement of purpose, motivation letter, essays the page sets),
`recommendation` (references, referee reports), `transcript` (transcripts, degree certificates,
proof of enrolment), `language_score` (an English or other language test report), `test_score`
(GRE, GMAT and the like), `portfolio`, `writing_sample`, `other` (anything else the page asks the
applicant to send: a research proposal, a passport copy, course descriptions; name it in `note`).
One entry per requirement: two different essays are two `personal_statement` entries.

### Conventions

The first extraction and its labels (11 programs, 2026-11-21) were made by two agents that did not see
each other's work. Calls 1 to 10 are ones both made, with the one departure noted under 8; 11 to 13
were settled afterwards, where the two differed or the brief was silent. Calls 14 to 22 were written
after the random sample of 30 programs (2026-11-21), from the gaps its extractor and its labeller
reported and from the five programs on which they differed; that sample was read and labelled before
these calls existed and was not changed to fit them. Follow all of them, so that a later run and a
later label agree.

1. **What counts as asking.** Only a sentence that asks the applicant to provide, submit, present,
   upload or include a document. A score threshold ("IELTS 6.5 overall"), "must demonstrate
   proficiency", an exemption ("not required to present TOEFL if…") and a negation ("references are
   not required") are not entries.
2. **A pointer is not a requirement.** "See the Supporting Documents PDF" or "find out more about
   references and personal statements" names a place, not a document: no entry. A page that only
   points elsewhere is `"materials": []`.
3. **Optional** materials are recorded, with "optional" in the note.
4. **Required of some applicants only**: recorded, with the condition in the note ("if first
   language is not English"), also when the page states the condition in another sentence than the
   one quoted.
5. **"May request"** ("we may request an additional reference") is not recorded and not counted.
6. **One statement answering several set questions** is one `personal_statement` entry; the
   questions go in the note.
7. **A sentence that says what a document must contain** ("the CV should highlight…") asks for the
   document.
8. **A sentence that asks for two kinds of material** ("may wish to include a CV or evidence of
   professional registration") is two entries with the same quote. When another sentence asks for
   one of the two more exactly (a footnote saying who must send the language scores), that entry
   quotes that sentence instead; the first extraction did, its label did not.
9. **`count` is a number of documents**, never years, pages, words, minutes or questions.
10. **Placeholders** ("any additional documents required for this programme") are not recorded.
11. **In a bulleted list** the quote is the item's own line. When that line is under 10 characters
    or does not name the material by itself ("references"), quote the sentence that introduces the
    list and the lines down to the item, as one unbroken stretch of the page.
12. **Translations** of academic documents are `transcript`, with "translation" and any condition in
    the note; so are translations of "your documents" where the page does not say which. When the
    sentence that asks for a document also asks for its translation, that is one entry with the
    translation in the note. A translation of another named document takes that document's type.
13. **Degree certificates, transcripts and proof of enrolment** are `transcript`. A certificate the
    page lists as its own item or sentence is its own entry with "degree certificate" in the note;
    "certificates and transcripts" in one item is one entry naming both. An academic proof the page
    names apart from these (a statement of the average mark, a list of current modules, evidence of
    a prerequisite such as A-level mathematics, course descriptions) is `other`, named in the note.
14. **A test or document named as required, without a verb.** A requirement field or a sentence
    that says the application needs it ("GRE Requirements" over "Yes, general test", "Supplementary
    Application" over "Required", "the GMAT is required") is an entry, typed by what it names; the
    quote is the field's name and its value as one unbroken stretch. What it names has to be
    something an applicant sends (a test score, a document, a form): "Interview: required" and
    "Supervisor required" are not entries. A threshold by itself ("IELTS 6.5 overall") is still not
    one (call 1). "Preferred but not required" and "recommended" make an optional entry (call 3);
    "not required" makes none.
15. **"You may need to provide" against "you may be asked to provide".** A document that depends on
    the applicant's own situation is recorded with the condition in the note (call 4): "you may need
    to provide a portfolio if your degree is in another subject"; so is a document the page accepts
    in place of something the main one lacks ("if your transcripts do not state this, a letter from
    the university … will be accepted"). When the page says "may need" and gives no condition, the
    note says "may be needed; the page does not say when". A document the school may ask for later,
    at its own choice ("you may be asked to provide", "we may request", "further documents may be
    required"), is not recorded (call 5).
16. **"Provide evidence of" an eligibility condition.** Evidence the page asks the applicant to
    provide for a condition whose proof is a document of its own (work experience, professional
    registration, funding) is `other`, with what it is evidence of in the note. Evidence of the
    degree or of grades is the transcript: `transcript`, and no second entry when the page already
    asks for transcripts. "Applicants must have two years of experience", with no "evidence",
    "proof" or verb of sending, is an eligibility rule and no entry (rule 3).
17. **Documents needed only after an offer, to enrol or for a visa** (official or paper transcripts
    once admitted, an ATAS certificate, bank statements for the visa, a deposit, health or police
    checks) are not recorded: the list is what the application itself needs. When the page asks for
    a document with the application and again in another form after an offer (uploaded copies now,
    official copies later), the entry is the application's, and "official copies after an offer"
    may go in its note.
18. **Sentences about programs in general** ("many programs require a portfolio", "some courses ask
    for a writing sample", "depending on the programme you may need…", "have your qualifications
    and resume ready to upload") do not say that this program asks: no entry. A sentence the page
    states for every applicant it covers ("all applicants must submit…", "you will need to provide
    the details of two referees") is recorded.
19. **"One or more of the following", "at least one of".** A choice among alternatives is not a
    count: no `count`; the note says "one or more of" and names the alternatives in a few words.
    `count` is for a number of documents of one kind: "at least two letters" is `count` 2 with
    "at least" in the note.
20. **A document and its verification by another body, asked for in one sentence** (a degree
    certificate and its CHSI verification report, a transcript and a credential evaluation) are two
    entries with the same quote (call 8): the certificate or transcript as `transcript`, the report
    as `other`, named in the note.
21. **What to write in the application form is not a document.** "Indicate in your online
    application which faculty member may supervise you and explain why" asks for no document unless
    the page names one (a statement, a letter, a research proposal): no entry.
22. **Notes on labels.** A label carries a `note` where rule 5 would give an entry one, and always
    on an `other` entry (its name), an optional one ("optional") and a conditional one (the
    condition). Notes are not scored (the unit is program and type), so a missing note is not an
    error of the set; like an entry's, a label's note holds no figure that is not in its quote.

### Commands

```bash
# 1. What to read: one line of JSON per program (id, page, snapshot, whether it is done).
.venv/bin/python -m app.collect.material_extract targets --school <school_key> --pending
.venv/bin/python -m app.collect.material_extract targets --program <program_id> --program <program_id>

# 2. Read one program's stored page. A long page is printed as the lines around material words;
#    --full prints all of it, --lines A:B a range.
.venv/bin/python -m app.collect.material_extract text <program_id> --school <school_key>

# 3. Hand in what the page asks for. The command checks every entry, writes the ones that pass into
#    the school's file and prints the refusals with their reasons. --dry-run checks without writing.
.venv/bin/python -m app.collect.material_extract accept <program_id> --school <school_key> \
    --extractor "<who you are>" --json api/var/work/materials/<program_id>.json

# 4. Take back a program you handed in by mistake (the text was a cookie wall, an error page,
#    another program). It is listed as pending again.
.venv/bin/python -m app.collect.material_extract withdraw <program_id> --school <school_key> \
    --reason "<what was wrong>"

# 5. Where the extraction stands.
.venv/bin/python -m app.collect.material_extract status --school <school_key>
```

The file you hand in:

```json
{
  "snapshot_sha256": "<the snapshot_sha256 that `targets` printed for this program>",
  "materials": [
    {"type": "recommendation", "count": 2, "note": "at least one academic referee",
     "quote": "Two references are required, at least one of which should be academic."},
    {"type": "cv", "quote": "Upload a current CV."}
  ]
}
```

A refused entry was refused for a reason the report names (`quote not found in snapshot`,
`count=3 not in quote`, …). Copy the quote again from the `text` output, or drop the entry. Never
change a count or a note so that it passes. Handing a program in again replaces what was written.

The snapshot store is `api/var/snapshots/`; when it lives elsewhere, set
`LEAPASHORE_SNAPSHOT_ROOT` to it for every command.

### What to report when you finish

One line of JSON: `{"programs_read": N, "handed_in": N, "entries_accepted": N, "entries_refused": N,
"pages_listing_none": N, "skipped": [{"program_id": "…", "why": "…"}]}`.

## Labelling a set to measure the extraction

`python -m evals.materials` scores an extraction against labels (`api/evals/materials.py` states the
format and the metrics). The labeller must not see any extractor's output: start from
`python -m evals.materials --template --program <id>… --out api/evals/materials_gold.json`, read each
page with the `text` command above (it prints no extraction state), fill in `materials` for every
program by the rules of the brief, set `labeller` and `labelled_at`, and run
`python -m evals.materials --check`. Do not open the requirement files while labelling.

The first set is `api/evals/materials_gold.json`: 11 programs, labelled on 2026-11-21 by a model (a
Claude subagent), not by a person; its score is `api/evals/results/materials-2026-11-21.json`. It is a
check that the pipeline works end to end, on programs that were chosen and not sampled, so it says
nothing about the rest of the catalogue (`docs/measurements.md`, "First material extraction").

The second is `api/evals/materials_gold_sample.json` (`--set` names it): 30 programs drawn at random
from the 7,540 that were on file, in the catalogue, had a stored page and were not yet extracted
(`api/evals/materials_sample_2026-11-21.json` holds the seed and the rule), labelled the same way on
the same day; its score is `api/evals/results/materials-sample-2026-11-21.json`. Its labels are a
model's too, it has 33 labelled (program, type) pairs, and 17 of its 30 pages list no document, so
read its figures with the caveats in `docs/measurements.md`, "Random-sample extraction".

A label covers the page it was written from. An entry that an extractor later reads from a linked
page (rule 6, `source_sha256`) is left out of the comparison and listed under
`entries_from_other_pages`.
