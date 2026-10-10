# OfferPilot

A long-horizon planning agent for master's applications to Australian universities. The product is a
**visual application roadmap**: open any phase and see what to prepare, when to prepare it, and which
official page the requirement came from.

## Current stage status

The repository provides the onboarding flow, the portfolio picker, the roadmap interface and the advisor
chat skeleton. A FastAPI service with a PostgreSQL schema persists the applicant's profile; the
application stage, the portfolio and the completed materials still live in `localStorage` and move to the
server in the next batch.

Not implemented:

- There is no agent and no model call. The advisor chat appends the message and answers with a fixed
  notice rather than pretending an assistant replied.
- No official deadline is recorded. Every program carries `dataStatus: "待核验"` and the interface says
  so.
- Admission thresholds come from a first-pass manual seed set that mirrors `web/lib/programs.ts`. A guard
  fails the test run if the seed and that file diverge, but neither has been checked against a university
  page. This is placeholder data pending the annotation stage.
- There is no file upload, no document review, and no review criteria.
- The backend has no authentication. A profile is scoped to an anonymous cookie, so clearing browser data
  loses access to it.

## Local setup

~~~bash
make install     # install dependencies
make dev         # http://localhost:3000
make verify      # build plus end-to-end walkthrough screenshots
make help        # list every command
~~~

If `npm install` fails with `EPERM`, the shared npm cache contains root-owned files. `make install`
already points npm at a repository-local cache directory to avoid that.

## Product flow

```
Onboarding (ten steps, green progress bar with an x/y counter)
  -> "background captured, generating a plan"
  -> Portfolio selection (reach / steady / safe)
  -> Main interface: home | roadmap | profile | advisor
```

The **roadmap** is the main surface: six phases stacked vertically, each showing preparation materials,
a suggested date, the official deadline, and the source. Ticking a material updates the phase status.

## Data honesty rules

These exist because the previous implementation of this product generated a plausible-looking
verification date and an official-looking threshold with no source. Do not undo them.

1. Admission data is marked `待核验` (pending verification) in `web/lib/programs.ts`.
2. `SourceCitation.verifiedAt` is `null`, not a hardcoded date.
3. Every date is a **system suggestion** derived backwards from the intake term. Official deadline
   fields are left empty and rendered as "pending verification".
4. When the system cannot decide, it returns "needs manual review" instead of guessing a tier.

## Interface language

Interface copy is Chinese because the product targets Chinese applicants. Source comments,
documentation, and commit messages are English. See CONTRIBUTING.md.

## Checks

~~~bash
make build        # type check and production build
make screenshots  # full walkthrough in a real browser, writes docs/screenshots/
~~~

The walkthrough uses the `@playwright/test` devDependency in `web/` and runs locally only. It needs a
Chromium build: run `npx playwright install chromium` in `web/` once if it is missing.

## How this differs from a support-chat agent

Both projects use a deterministic workflow with an agent layer, but the object under management is
different. A support agent aims to **answer a question correctly**. OfferPilot aims to **keep a
multi-month application state correct**, where every fact has to trace back to an official page.

That pushes the architecture toward source versioning and human review, freshness gates, refusing to
answer when evidence is missing, and confirmation before irreversible writes.

## Project records

- [Contribution and commit rules](CONTRIBUTING.md)
- [Repository instructions for agents](AGENTS.md)
- [English verification report](docs/verification/stage-1-skeleton.md)
- [Original Chinese verification record](note/verification/stage-1-skeleton.md)
- [Chinese stage design record](note/superpowers/specs/2026-10-05-stage-1-mvp-design.md)
- [Chinese stage implementation plan](note/superpowers/plans/2026-10-05-stage-1-mvp.md)
- [Chinese learning log](note/stage-1-MVP.md)
