## Context

TASKS.md P1 #1. Collection files (`api/data/requirements/*.json`) carry `academic` (a summary `text`
plus its quote) and `deadlines` (a list of `label`, ISO `date`, quote, optional shared page) per
program; `verify` has already checked each quote against its snapshot (`check == "ok"`). Owner
authority for this item: TASKS.md 2026-10-30 (choices are Claude's, recorded in note/decisions.md).

## Decisions

- **D1 Deadlines get their own table, the academic summary a column.** A program has 0..n deadlines
  (rounds, intakes; up to 7 in the data) and one academic summary. `program_deadlines` keeps the label
  and date as collected, the verified quote, and the page the quote is on (`source_url` of the item,
  else the program page). Row ids are `uuid5(program#deadline#index)`, like prerequisites, because one
  program lists the same (label, date) twice. `programs.academic_source_url` keeps the page the
  academic quote is on, for the same reason: 725 of 4,831 academic quotes and 746 of 3,986 deadline
  quotes are on a shared admissions page, not the program page.
- **D1a The advisor cites where a value is.** An evidence line names the page of an academic
  requirement or a deadline read from a shared page (`（出处 url）`), and the prompt tells the model to
  give that link rather than the program page's.
- **D2 Deadlines are not written into `applications`.** `applications.official_deadline` is a value
  someone entered for one applicant (the API accepts it; the advisor may write it). The import fills
  the catalogue only, and the portfolio read serves the program's deadlines beside the row's own date.
  "Never overwrite an entered date" then holds by construction: the import has no write path to
  `applications` or `roadmap_tasks`.
- **D3 Which deadline a portfolio row shows.** The row's own date when it has a date and a source url;
  otherwise the earliest collected deadline on or after today; otherwise, when every collected
  deadline is past, the latest one labelled 已截止; otherwise 未收录. Only the first two are drawn on
  the timeline, and only inside its date range.
- **D4 "Today" is the Beijing calendar date at render time** (`Asia/Shanghai`), on the server-rendered
  program page and in the browser alike, so the two never disagree. A deadline on today's date is still
  open. Nothing stores "closed": it is derived each time, so it cannot go stale.
- **D5 Idempotent import.** The academic summary and its page ride with the other requirement columns (replaced
  as one set when the program has any verified value; untouched otherwise). Deadlines are compared
  with what is stored and rewritten only when they differ (prerequisites too), so a rerun issues no
  INSERT, UPDATE or DELETE and leaves `updated_at` alone; the test counts the statements.
- **D6 The stated-requirement rule** adds `academic_requirement IS NOT NULL` and "has a deadline".
  Both are shown on the program page under 录取要求, so a counted row always has something to show.
- **D7 Text-only English (30 programs) and Chinese-applicant notes (55)** stay out of scope: they are
  descriptions without a number, and showing them needs its own wording decision. Recorded as open.

## Risks

- Labels and academic summaries are the collector's English wording, not a quote; the page shows the
  quote's source link next to them, and the program stays 待核验 until a person reviews it.
- A deadline for a later intake than the applicant's can be picked as "next"; the label is shown with
  the date so the applicant can tell.
