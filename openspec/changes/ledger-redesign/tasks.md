## 1. Application status (backend)

- [x] 1.1 Red: tests that `PUT /api/applications` accepts `submitted`, `offered`, `rejected` and refuses `waitlisted` with 422 and no change
- [x] 1.2 Green: add the three values to `ApplicationStatus`; update the advisor portfolio tools and their tests
- [ ] 1.3 Add the six display names to `web/lib/taxonomy.ts` and the client types in `web/lib/types.ts`

## 2. Program catalog (backend)

- [x] 2.1 Write the placeholder-slug → CRICOS-code map after confirming each course's name and provider in the extract; record any slug with no match
- [x] 2.2 Red: tests for the catalog seed — one `cricos-` row per extract course, university per provider, CRICOS source row, empty requirements, `待核验`, no `verified_at`, idempotent second run
- [x] 2.3 Red: tests for the fold — requirements and source move onto the matched row, `applications` re-pointed with first choice and status kept, no placeholder row left, unmatched slug dropped
- [x] 2.4 Green: `api/app/seed_catalog.py` with the upsert and the fold; wire it into `make seed`
- [x] 2.5 Red then green: `GET /api/programs` filters `ids`, `field`, `provider`, `has_requirements`, `limit`, `offset`, with a 100-row cap
- [x] 2.6 Advisor: test that `search_programs` finds a CRICOS course by English name and still returns at most 10
- [x] 2.7 Run the backend suite on a fresh database (`make migrate`, `make seed`) and fix fallout from the larger catalog

- [x] 2.8 (D11) File collected programs under a study area read from their name; test agreement with CRICOS
- [x] 2.9 (D11) `GET /api/programs` gains `q` and serves `universityId` and `country`
- [x] 2.10 (D11) `GET /api/universities` lists each school row with its program counts; `provider` takes several ids

## 3. Tiering and data adapters (web/lib)

- [x] 3.1 Red: `lib/tiers.test.ts` covering every `program-tiering` scenario (safety, reach, two shortfalls, 要求未收录, text-only English, unknown / overseas / non-211 institution)
- [ ] 3.2 Green: move `prototype-tiers.ts` to `tiers.ts` on the API program shape; remove the `信息不足` tier; delete `eligibility.ts`
- [ ] 3.3 Rename `prototype-library-server.ts` to `catalog-server.ts`; test the join by course code against `/api/programs`
- [ ] 3.4 Add `web/lib/hooks/` (`useProfile`, `usePortfolio`, `useRoadmap`, `useMaterials`), each `{ data, error, loading, reload }`, with tests for the error path
- [ ] 3.5 Remove the default intake from `lib/roadmap.ts`; test that a profile without an intake yields undated phases
- [ ] 3.6 One display map from stored values to interface words (PRD §7.7 rule 5) in `lib/taxonomy.ts`, with a test that every stored status has a label

## 4. Visual system and shell

- [ ] 4.1 Replace `app/globals.css` with the personal-site tokens (D7); system font stack, no web font
- [ ] 4.2 Build `components/ui/` primitives: Button (primary, secondary, text), Field, Select, Pill, Table, Panel, Empty, Notice
- [ ] 4.3 Draw the product mark (SVG) and build the shell: top bar, five links, 我的背景, `aria-current`, phone menu
- [ ] 4.4 Inspect the empty shell with the taste-skill inspector at 1440 and 390; fix every FAIL

## 5. Routes and pages

- [ ] 5.1 `proxy.ts`: return-visit redirect from the API profile with `API_ORIGIN` and a one-second timeout; remove the onboarded cookie; tests for complete, incomplete, and API-down
- [ ] 5.2 `/` introduction for first visits
- [ ] 5.3 `/assess`: the ten-question single page, school search with Ministry tags, required-field messages, save-then-navigate, failed-save state
- [ ] 5.4 `/assess/result`: tiers, 去官网确认 notes, the 要求未收录 list and count, add to draft with band picking for untiered programs
- [ ] 5.5 `/portfolio`: rows with band, needs-review, official deadline or 待核验, status select, first-choice mark, confirm with count, empty state
- [ ] 5.6 `/roadmap`: the SVG timeline (dashed, solid, hollow marks, legend, today line, current phase, overdue mark), vertical axis below 640px, no-intake state
- [ ] 5.7 `/roadmap` phase detail: tasks with ticks via `PATCH`, failed-tick rollback, upload from a task row
- [ ] 5.8 `/me`: profile summary with edit link, materials library (list, download, archive, submit, view reviews), settings
- [ ] 5.9 `/advisor` restyled on the shell; emoji removed; confirm flow unchanged
- [ ] 5.10 `/schools` and `/schools/[provider]` as rule-separated rows, no consultation buttons
- [ ] 5.11 `/programs` and `/programs/[code]`: CRICOS facts, requirements or 未收录, add to draft
- [ ] 5.12 Loading, empty, and error states for every block, checked in the browser

## 6. Walkthrough and removal

- [ ] 6.1 Write `scripts/walkthrough.cjs` over the new routes at 1440 and 390, failing on console errors, sideways scroll, or a missing `h1`; point `make screenshots` at it
- [ ] 6.2 Delete the old screens (`AppShell`, `FlowView`, `HomeView`, `MaterialsView`, `ProfileView`, `SettingsView`, `PortfolioPicker`, `Generating`, `Onboarding`, `AdvisorView` once replaced), `app/prototype/`, `components/prototype/`, `lib/store.ts`, `lib/prototype-handoff.ts`
- [ ] 6.3 (10-29: verify-programs-mirror.cjs and seed-programs.snapshot.json deleted; lib/programs.ts and check-no-programs-import.cjs remain) Delete the six-program mirror (`lib/programs.ts`, `verify-programs-mirror.cjs`, `check-no-programs-import.cjs`, `seed-programs.snapshot.json`) and its Makefile targets; delete the sample requirements and states from `prototype-fixtures/data.ts`
- [ ] 6.4 Delete `scripts/e2e-walkthrough.cjs` and `docs/screenshots/01…29` and `docs/screenshots/prototype/`

## 7. Verification

- [ ] 7.1 Inspector on the production build for every page at 1440, 768, 390: 0 FAIL; each WARN fixed or defended in `note/`
- [ ] 7.2 Look at every screenshot; write the app-screen critique; fix the worst three; repeat at most three rounds
- [ ] 7.3 Fresh-context review of the diff against the six specs; fix correctness gaps
- [ ] 7.4 `make verify` with `NODE_ENV` unset; paste its output into the report
- [ ] 7.5 Update `note/handoff.md`, the PRD §4 status table, and `README` screenshots
