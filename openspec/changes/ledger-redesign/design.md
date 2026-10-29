## Context

Two frontends share `web/`. The original flow (`app/page.tsx`, about 900 lines, plus `components/*View.tsx`)
holds the applicant's state, reads and writes the API, and renders onboarding, portfolio, roadmap, materials,
profile, and settings in a bright-green style. The prototype (`app/prototype/*`, `components/prototype/*`)
renders the school library, program library, assessment, advisor, applications kanban, and a consultant back
office in Tailwind's default emerald and slate, reading local fixtures. Since PR #24 the onboarding hands off to
the prototype and `proxy.ts` redirects returning visitors there, so the original flow's screens are unreachable.

The data disagrees with itself. The program library and the prototype tier engine (`lib/prototype-tiers.ts`) use
2,920 CRICOS courses and nine sample requirement sets from `prototype-fixtures/`. The backend catalog holds six
placeholder programs; the portfolio (`applications`), the roadmap tasks, the advisor's `search_programs` tool,
and a second tier engine (`lib/eligibility.ts`) all use those six.

Constraints: PRD red lines (no invented requirements or deadlines, unknown stays unknown, `verified_at` only by
a human, sample data marked at every occurrence); no new npm or Python dependency; no database migration; the
API stays the browser's only path to applicant data.

## Goals / Non-Goals

**Goals:**

- One route map and one shell, with the roadmap reachable as the main interface.
- One assessment, one catalog, one tier rule, one portfolio with statuses, all backed by the API.
- One visual system applied to every page, checked by the taste-skill inspector at 1440, 768, and 390 px.
- `make verify` still drives every page in a real browser.

**Non-Goals:**

- Collecting real admission requirements (the next item in the handoff).
- Sign-in, the consultant back office, lead capture.
- Countries other than Australia in the program catalog; the school library keeps its schools (346 then, 287 since the 2026-10-30 scope change).
- A Postgres checkpointer for the advisor.
- Deployment. The new seed must run in production before this version ships; that is a separate step.

## Decisions

### D1. Each route owns its data; no global store

Each page is a client component that loads what it shows through `lib/api.ts` and keeps it in local state.
`lib/store.ts` and the `localStorage` mirror go. Shared reads (the profile, the portfolio) use one small hook per
resource in `web/lib/hooks/`, each returning `{ data, error, loading, reload }`.

- *Why not keep one orchestrator?* `app/page.tsx` mixes six screens' state in one component, which is why the
  roadmap disappeared when the routing changed. Per-route ownership makes a page reachable by URL and testable
  alone.
- *Why not a state library?* It would be a new dependency, and the server is already the source of truth.

The existing adapters stay: `programs-source.ts`, `roadmap-source.ts`, `roadmap-sync.ts`, `roadmap.ts`,
`roadmap-definition.ts`, `materials-source.ts`, `source-status.ts`.

### D2. The return-visit redirect asks the API

`proxy.ts` matches `/`, forwards the visitor's `leapashore_client` cookie to `GET {API_ORIGIN}/api/profile`, and
redirects to `/roadmap` when every required field is present. `API_ORIGIN` defaults to `http://127.0.0.1:8000`
for local runs; production sets it to `http://api:8000`. If the API does not answer within one second, `/`
renders the introduction. The `leapashore_onboarded` cookie is removed.

- *Alternative:* keep the cookie. Rejected because the spec requires the redirect to survive cleared storage
  and to follow the server's profile, and a cookie can claim completion the server does not hold.

### D3. The catalog: facts from the CRICOS file, identity and requirements from the backend

A new seed, `api/app/seed_catalog.py`, reads `web/prototype-fixtures/cricos-au-masters.json` and writes one
`universities` row per provider (Chinese name taken from `overseas-institutions.json` where the provider matches,
otherwise the CRICOS name) and one `programs` row per course, id `cricos-<code>`, `name` and `name_en` set to
the CRICOS course name, `field` the CRICOS broad field, `duration` `<weeks> 周`, every requirement column empty,
`data_status` `待核验`, and one shared `sources` row for the dataset. It upserts, so it is idempotent.

Pages that show catalog facts the table has no column for (tuition, total cost, narrow field) keep reading the
same JSON file on the Next server through `lib/prototype-library-server.ts` (renamed `lib/catalog-server.ts`),
joined to the backend by course code. Both sides read one file, so they cannot drift apart unless the file is
replaced without re-running the seed; the walkthrough checks one course on both sides.

- *Alternative:* add tuition columns. Rejected: a schema change for display-only facts.
- *Alternative:* serve all 2,900 programs to the browser for tiering. Rejected: about 1.7 MB per load. The result
  page fetches only programs with collected requirements (`has_requirements=true`) and the count of the rest.

### D4. The six placeholders fold into their CRICOS rows

The seed carries a fixed map from each placeholder slug to its CRICOS course code, confirmed by reading the
course name and provider in the extract while writing the map. For each pair it copies the minimum marks,
prerequisites, English requirement text, and official source onto the CRICOS row, re-points `applications` and
any task or document reference, then deletes the placeholder row. A slug with no matching course is dropped with
its requirements, and the seed prints which. `seed-programs.snapshot.json`, `web/lib/programs.ts`,
`verify-programs-mirror.cjs`, and `check-no-programs-import.cjs` go with the mirror they guarded.

### D5. One tier engine, on the backend's program shape

`lib/prototype-tiers.ts` becomes `lib/tiers.ts`, takes the API's program shape and the server profile, and
implements the `program-tiering` spec. `lib/eligibility.ts` is deleted. The thresholds remain named constants in
that file. The nine sample requirement sets and sample application states leave `prototype-fixtures/data.ts`.

### D6. Application status grows to six values

`ApplicationStatus` gains `submitted`, `offered`, and `rejected`. The column is `String(16)`, so no migration;
the API schema, the advisor's portfolio tools, and their tests change. Display names live in one map in
`web/lib/taxonomy.ts`.

### D7. The visual system: the owner's personal-site palette on the ledger structure

The structure comes from the taste-skill app draw (`achromatic-ledger`, seed 1663361703): colour on data and on
the one primary action, flat surfaces, rows instead of cards. The palette and type come from the owner's personal
site (mortyyjt.github.io), chosen by MortyYJT on 2026-10-29 after comparing three dealt palettes, so the product
and the site read as one family once both live under `mortyyjt.site`.

- **Tokens** in `app/globals.css` `@theme`: canvas `#fbf6ec`, surface `#fffdf8`, raised `#f3ede1`, border
  `#ece4d6`, rule `#f3ece0`, control `#d8cfbf`, text `#3d3a35`, muted `#6b655c`, accent `#4a9b78` (shapes only:
  3.1:1), accent text `#2f7a5a` (4.8:1), primary fill `#357a5c` (white label 5.1:1), active `#dcefe3`, negative
  `#c4242a`. Radii 20 (panels) and 12 (controls); lines are 6-7% warm grey, not solid beige.
- **Taken from the site's look, toned down** (MortyYJT, 2026-10-29: the flat version read as stiff): the site's
  three radial blobs as a fixed wash behind the page, with its 4.5% grain; panels at 86% opaque warm white with an
  18px backdrop blur, a white top highlight, and a `0 6px 24px` 8% warm shadow (under the inspector's
  `heavy-shadow` limit). No gradient on any panel, button, or text. The `palette-cream` warning is accepted: it is
  the owner's brand, not a template default.
- **Type**: the system stack (`-apple-system`, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans SC), as
  on the site. No web font, so nothing loads from outside the app's origin. Sizes 24 / 16 / 14 / 12, figures 30;
  tabular figures on every number.
- **Shell**: a 48px top bar on the canvas over a centred 1152px column. The mark is a small SVG drawn for this
  product (an arc leaping over a line) in the accent; the selected nav item is a pale-green pill with ink text.
- **Rows, not cards**: lists (schools, programs, portfolio, tasks, materials) are tables or rows with 1px rules.
- **Accent budget**: the roadmap's today line and current phase, the mark, the selected nav pill, the one primary
  button per screen, and the tier pills. Status uses the pale pill pairs; 示例 keeps its amber pair.
- **Words**: data states use the display map of PRD §7.7 rule 5; a task list says once that its steps are system
  suggestions instead of repeating it per row; each program's items to check are one line (去官网确认 N 项).
- **Motion** (the site's `card-in`: rise, fade, sharpen): panels enter once per page load, staggered 70ms; on the
  roadmap the panel lands first, then the today line draws down and the phase bars grow left to right, 60ms
  apart, about 1.6s in all. Switching phase crossfades the detail; ticking, pressing, and hovering give feedback;
  re-renders never replay an entrance. `prefers-reduced-motion` removes all of it.
- **Removed devices**: the label above every title, arrows appended to button text, the floating button, emoji,
  the per-card data-source line (each page cites its sources once in a footer note).
- Tailwind v4 stays. A few shared primitives in `components/ui/` carry the tokens.

### D8. The roadmap timeline is SVG drawn from data

The axis is a React component that maps dates to x with one linear scale from today to the intake anchor; phase
spans, the today line, and three mark kinds (dashed suggested, solid official, hollow 待核验 in a lane after the
axis's end, because an unknown date has no x) are SVG shapes. Labels sit in rows above the plot so they never
collide. Below 640px the axis turns vertical (time runs down) so labels keep 14px. No chart library.

### D9. Sample data

After D3–D5 no sample requirement or sample status reaches the interface. If any sample value remains, each
occurrence is marked 示例 (PRD §7.7 rule 4). The school-tier tags shown as 自动标注 on the assessment are
real Ministry data and keep their own label.

### D10. A new walkthrough replaces the old

`scripts/walkthrough.cjs` (Playwright, already a dev dependency) drives a fresh visitor through `/` → `/assess`
→ `/assess/result` → `/portfolio` (confirm) → `/roadmap` (tick, upload) → `/me` → `/advisor` → `/schools` →
`/programs/<code>`, at 1440 and 390 px, writes `docs/screenshots/NN-*.png`, and fails on a console error, a
horizontal scroll, or a missing `h1`. `make screenshots` points at it; the old script and screenshots 01–29 are
deleted.

### D11. The catalog is no longer Australian only (added 2026-10-29)

Since this design was written, the requirement importer has added 5,337 programs at 141 schools in many
countries (PR #27). D3's premise that every non-hand-entered program is a CRICOS course no longer holds, so:

- **Study areas from names.** A collected program has no official field, so the importer files it under a
  study area read from its English name (`app/collect/fields.py`, ordered keyword rules). The rules agree with
  CRICOS's own field on 78.5% of the 2,920 Australian courses; the remaining differences are mostly CRICOS's
  own filing (it puts clinical medicine under natural sciences and software engineering under engineering).
  A name no rule matches stays unclassified. A row that already has an area, such as a CRICOS row, keeps it.
  The area is a filing label for search, never an admission fact.
- **The library and the result page read the API.** `/programs` lists `GET /api/programs` with a new `q`
  search and paging; Australian rows add the CRICOS facts (tuition, weeks) by course code as D3 says. The
  result page tiers every program in the target field that has a stated requirement, whatever its country.
- **Programs link to their school.** `GET /api/programs` serves `universityId` and `country`. The school library
  keeps its schools (287 since 2026-10-30) from `overseas-institutions.json` and joins them to `GET /api/universities` by Chinese
  name, then English name. One school can have several rows (CRICOS lists some universities under two
  provider codes, and the importer leaves an empty row for a school whose site refused collection), so a
  school page reads its programs with `provider=<id>,<id>`. School pages are addressed by the library's own
  slug (`/schools/[slug]`), which every school has, rather than by a backend id only some have.

## Risks / Trade-offs

- [Most programs have no requirements, so the result page tiers only a handful] → The page leads with the count
  under 要求未收录 and lets the applicant add any program with a band they pick; collecting real requirements is
  the next change.
- [`/api/programs` now caps at 100 and the advisor's search sees 2,900 rows] → The web client always passes
  filters; the advisor tool already limits to 10 and its tests gain a case against the larger catalog.
- [The production database still has placeholder rows and applications pointing at them] → The fold is part of
  the seed and re-points before deleting; it is run once on deploy, and the migration plan below says how to
  check it.
- [`proxy.ts` now calls the API on every visit to `/`] → One-second timeout and fallback to the introduction;
  only `/` is matched.
- [Deleting the old screens removes working upload and review UI] → The `document-library` interface
  requirement is re-checked by the new walkthrough before the old code is deleted.
- [`next/font/google` needs network at build time] → Local and production builds already have network; if it
  fails, the build fails loudly rather than shipping a fallback face.

## Migration Plan

1. Backend first: status values, catalog filters, the catalog seed with the fold. Tests green.
2. Frontend routes and pages on the new shell, alongside the old code.
3. The new walkthrough passes; then delete the old screens, fixtures, mirrors, and screenshots.
4. Deploy (separate step): run the catalog seed once, confirm `SELECT count(*) FROM programs WHERE id NOT LIKE
   'cricos-%'` is 0 and no application points at a missing program.

Rollback: the seed only adds rows and re-points six slugs; restoring from the pre-deploy database dump undoes it.

## Open Questions

- PRD §7.6 lists six roadmap phases; the backend definition has seven (it adds 签证与行前). This change draws
  whatever the API returns and leaves the PRD text for the owner to reconcile.
- PRD §7.2 says 保底 means all requirements are met. The `program-tiering` spec tiers on the requirements that
  can be compared and flags the rest as 去官网确认. The PRD owner should confirm this reading.
- PRD §7.2 says schools outside 985 / 211 always need human review; the spec still compares a program's own
  collected non-211 threshold. Confirm.
