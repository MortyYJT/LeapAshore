# LeapAshore rules (single source of truth)

## Workflow

- All development is done by Claude. Claude opens and merges every PR, then deploys.
- Work from `TASKS.md`, in order.
- Large changes (database schema, new subsystem, architecture): write an OpenSpec change first. Small
  features start straight from the task list.
- TDD for logic: write a failing test first, then make it pass. Docs and styling skip TDD.
- Before saying "done", run `make verify` (build, unit tests, browser walkthrough) and show the output.
- Before merging, a fresh-context subagent reviews the diff and reports only correctness bugs.
- Work on a `claude/<topic>` branch; never push to `main`. Merge only after CI passes.
- Commit format: `type(scope): summary`, body as English `- ` bullets.

## Ask the user first

- Design choices (architecture, tech selection) not already settled in `TASKS.md`: offer options; the
  user picks and gives a reason. Record it in `note/decisions.md`.

## Records

- Keep `note/handoff.md` current: what is done, what is next, open questions.
- Task list: tick an item when it is done and add the PR number.

## Red lines

- Never commit secrets, `.env` files, the owner's real name or private email, or identifying local
  paths. Identify the owner only as `MortyYJT`.
- Never invent admission requirements, deadlines, thresholds, or sources. Every fact traces to an
  official page, or is marked `待核验`.
- `verified_at` is written by a person, never by a default, an importer, or a job.
- Unknown stays unknown: never an empty string or a zero.
- The advisor must not state a judgement it cannot source.
- Collection obeys robots.txt and per-domain rate limits; a 403 or 429 is recorded, never bypassed.

## Project facts

- LeapAshore (鱼跃彼岸): an application-planning agent for overseas master's programs. Product
  requirements: `docs/product/PRD.md`.
- Next.js + TypeScript in `web/`; FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16 in `api/`; the
  LangGraph advisor in `api/app/agent/`; requirement collection in `api/app/collect/`.
- `make install`, `make dev`, `make verify`; `make help` lists the rest.
- The owner's shell exports `NODE_ENV=development` and `NODE_DEBUG`; unset both before building.
- Collected requirements: `api/data/requirements/*.json`. Page snapshots: `api/var/snapshots/` (local,
  not in git); production keeps its own in the worker's `snapshots` volume. The advisor quotes the cited
  pages' text from the `snapshot_chunks` table (no paths stored).
- Deploy steps and known pitfalls: `note/handoff.md`.
