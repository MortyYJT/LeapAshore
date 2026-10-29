## Why

The collection files hold 3,986 machine-checked application deadlines (2,335 programs) and 4,831
machine-checked academic requirements, but the importer drops both: the catalogue has no column for
them. The roadmap's "official deadline" lane therefore reads 未收录 for every program, and 350
machine-checked programs show no requirement at all on their page. Deadlines also age: 130 of them
are already before 2026-10-30, so a stored date cannot be drawn as a future milestone without
checking it against today.

## What Changes

- **Schema (Alembic, add only):** `programs.academic_requirement` (text, nullable) and a new table
  `program_deadlines` (program, label, date, quote, source page, order).
- **Importer:** writes the verified academic summary and the verified deadlines as part of the
  program's requirement set; a rerun writes nothing. It still never writes `verified_at`, and a field
  that failed its check stays null / absent.
- **API:** `GET /api/programs` serves `academicRequirement` and `deadlines`; the portfolio read
  (`GET /api/applications`) serves the program's collected `deadlines` beside the row's own
  `officialDeadline`, which the import never touches.
- **One "has a requirement" rule** grows to include an academic requirement or a deadline, in
  `has_requirement_data()` and in the frontend's `statesARequirement`.
- **Roadmap and portfolio:** a portfolio row's deadline is the row's own date when it has one (entered
  by the applicant or the advisor), otherwise the program's next collected deadline, drawn solid with
  its source link. A deadline before today (Beijing date, at render time) is labelled 已截止 and is not
  drawn on the timeline.
- **Program page:** shows the academic requirement and every deadline, past ones marked 已截止.
- **Advisor evidence:** each evidence line carries the academic requirement and the deadlines, past
  ones marked 已截止, since the gate now admits rows that state only these.
- **Data fix:** NTU's 8 TOEFL minimums on the new 1–6 scale are written as such, not as `TOEFL iBT 4.5`.

## Impact

- Code: `api/app/models/program.py`, `api/app/collect/importer.py`, `api/app/routers/programs.py`,
  `api/app/routers/applications.py`, `api/app/schemas/{program,application}.py`,
  `api/app/agent/evidence.py`, `web/lib/{catalog,deadlines,types,programs-source}.ts`,
  `web/app/roadmap/page.tsx`, `web/app/portfolio/page.tsx`, `web/app/programs/[id]/page.tsx`,
  `web/components/roadmap/Timeline.tsx`.
- Migration `b7d4e2a91c60` (add column, add table). Production: back up, migrate, rerun the importer.
- No change to `applications` or `roadmap_tasks`: an entered date cannot be overwritten by the import
  because the import never writes those tables.
