# Admission requirements collected from official program pages

One JSON file per school, `<school_key>.json`, for the taught master's programs of the QS 2027
top-200 schools outside mainland China. `_schools.json` lists the schools in collection order
(`wave` 1 = Australia, 2 = Hong Kong, 3 = Singapore, 4 = UK, 5 = US, …).

Every value here was copied from an official page **with a verbatim quote**, and `verify.py` checked
the quote against a stored snapshot of that page. `status` is `机器核对` (machine-checked) only when
every reported value passed; otherwise `待人工` (human queue). Nobody has verified these by hand:
nothing here is `已核验`, and no file carries `verified_at`.

Snapshots (raw HTML + text) live in `api/var/snapshots/<school_key>/<sha256>.*`, which is not
committed. Each program cites its snapshot by sha256, so the exact page version is identifiable.

## Brief for a collecting agent

You collect one school. Work from the repository root `/Users/yu-junteng/Documents/leapashore`.
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
   WebSearch / WebFetch may be used **only to find URLs**, never as the source of a quote.
3. **If the tool prints `{"blocked": …}` (403, 429, or robots.txt), stop fetching that host.** Do not
   retry with other URLs on the same host to get around it, and never change the User-Agent.
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
  previous year") is an inference and fails the check. Numeric dates are read in the school's own
  order: month first for the US (`12/01/2026` = 1 December 2026), day first everywhere else; set
  `country` exactly as `_schools.json` gives it.
- Run `verify.py --write` last; it adds `check`, `status`, and `verification`.

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
