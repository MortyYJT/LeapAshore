## Why

The product is two frontends glued together, and the main interface cannot be reached. Onboarding ends on
`/prototype/assess/result`, and `proxy.ts` sends every returning visitor to `/prototype`, so the roadmap,
portfolio, and materials screens (the PRD's "规划与执行" half) are no longer reachable. The two halves also
disagree on data: the program library and the assessment read 2,920 CRICOS programs from local files, while
the portfolio and roadmap store choices against six placeholder programs in the backend. Decision D1 in the
PRD already says how they merge; this change carries it out and gives the merged product one visual system.

## What Changes

- **One set of routes in one shell**: `/` (first visit: what this is and two ways in; returning visitor:
  redirected to the roadmap), `/assess`, `/assess/result`, `/portfolio`, `/roadmap`, `/schools`,
  `/schools/[provider]`, `/programs`, `/programs/[code]`, `/advisor`, `/me`. The `/prototype/*` routes are
  removed. **BREAKING** for any bookmark of `/prototype/*`.
- **One background assessment**: a single page holding the onboarding's ten questions, read from and saved
  to `/api/profile`. It replaces both the ten-step questionnaire and the prototype's assess form; the
  `sessionStorage` background is dropped.
- **One program catalog in the backend**: a seed imports the CRICOS master's programs into `programs`
  (no table change). Admission requirements stay empty and `待核验` unless an official source exists. The
  six placeholder programs no longer exist as separate rows.
- **One tiering rule**, PRD §7.2: the `信息不足` tier is removed; programs whose requirements are not collected
  are listed apart as `要求未收录`; institutions outside 985 / 211 return `去官网确认`.
- **Portfolio absorbs the applications kanban**: one row per program with the first-choice mark and an
  application status. **BREAKING** (API): `ApplicationStatus` gains `submitted`, `offered`, and `rejected`
  (the column is a plain string; no migration).
- **Roadmap as the main interface**: the phases from `/api/roadmap` drawn on a time axis from today to the
  intake. Official deadlines, system-suggested dates, and unverified deadlines each have their own mark, and
  every suggested date says it is not official.
- **Hidden**: `/admin`, the floating 联系顾问 button, and the in-page consultant forms.
- **Removed**: the old green interface (`AppShell`, `FlowView`, `HomeView`, `MaterialsView`, `ProfileView`,
  `SettingsView`, `PortfolioPicker`, `Generating`, `Onboarding`), `lib/store.ts`, the duplicate tier engine,
  the six-program mirror (`web/lib/programs.ts` and its two check scripts), the sample requirements and
  sample application states in `prototype-fixtures`, the old walkthrough `scripts/e2e-walkthrough.cjs`, and
  `docs/screenshots/01…29`. A new walkthrough over the new routes replaces it, so `make verify` still drives a
  real browser.
- **One visual system** taken from the owner's personal site (mortyyjt.github.io): cream canvas, warm ink,
  sage green on the roadmap's today line, current phase, and the primary action, soft radii, flat surfaces with
  no shadows or gradients, the system font. The interface uses applicant words for data states (PRD §7.7
  rule 5) and names the tiers 保底 / 稳妥 / 冲刺.

## Capabilities

### New Capabilities

- `app-navigation`: the route map, the shell and its navigation, what a first visit and a return visit see,
  and what is hidden.
- `background-assessment`: the single assessment page, its required fields, and reading and writing the
  profile through the API.
- `program-catalog`: the backend program catalog seeded from CRICOS, how unknown requirements are stored and
  shown, and the sources it cites.
- `program-tiering`: the reach / match / safety / not-met rule, the `要求未收录` list, and the institutions
  that need human review.
- `application-portfolio`: choosing programs from the results, the single first choice, the application
  statuses, and confirming the portfolio.
- `application-roadmap`: the timeline from today to the intake, the three kinds of date mark, phase status
  from task ticks, and uploading materials from a task.

### Modified Capabilities

None. `document-library`'s interface requirement (upload from a task row, list, download, archive, submit)
still holds; only the page that hosts the list moves to `/me`.

## Impact

- **Web**: almost every file under `web/app` and `web/components` is rewritten or deleted; `web/lib` keeps
  its API client and source adapters, loses `store.ts`, `programs.ts`, and one tier engine.
  `web/app/globals.css` is replaced. No web font.
- **API**: `ApplicationStatus` gains three values; `/api/programs` serves the CRICOS catalog (size grows from 6
  to about 2,900 rows, so it gains filtering and paging parameters).
- **Data**: a new seed for the CRICOS catalog; existing `applications` rows that point at a placeholder slug
  are re-pointed to the matching CRICOS row or removed (local and production databases).
- **Checks**: `make test` drops the two mirror checks; `make verify` runs the new walkthrough.
- **Deploy**: the production database needs the new seed run once. Deployment itself is not part of this
  change.
