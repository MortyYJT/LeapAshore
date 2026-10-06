# OfferPilot

A long-horizon planning agent for master's applications to Australian universities. The product is a
**visual application roadmap**: open any phase and see what to prepare, when to prepare it, and which
official page the requirement came from.

## Current stage status

The repository provides the onboarding flow, the portfolio picker, and the roadmap interface. State is
kept in the browser.

Not implemented:

- There is no backend service. State lives in `localStorage`, not on a server.
- There is no agent and no model call. The advisor tab is a placeholder describing intended behavior.
- Official deadlines are **all marked as pending verification**. No deadline has been confirmed against
  a university page.
- Admission thresholds come from a first-pass manual seed set. Every record carries
  `dataStatus: "待核验"` and the interface surfaces that to the user.
- There are no unit tests yet. `lib/` holds pure functions that should be covered by tests.
- The CI workflow exists but **has never run on GitHub**. Deployment and containers are not verified.

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

The walkthrough borrows Playwright from a sibling checkout, so it runs locally only.

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
