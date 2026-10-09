# Repository instructions

Applies to the whole repository. Higher-priority instructions and the user's explicit scope win over this
file. Keep this file short; details live in [docs/engineering/agent-guidelines.md](docs/engineering/agent-guidelines.md)
and are read on demand.

This file and its companions came from a template shared by several agents. **Where a name does not fit
this project or the agent reading it** — a branch prefix, a command, a path into an agent-specific
directory — adapt it and say what you changed. Adapt the form freely; do not drop a rule because it is
inconvenient.

## Always apply

- Check premises, logical gaps, and missing information before acting. Judge independently; separate
  facts, inferences, predictions, and preferences. Never invent results.
- Never commit secrets, `.env` files, private contact details, the owner's real name, or identifying local
  paths. Identify the owner only by their public handle.
- Talk to the user in Chinese. Write source comments and engineering docs in English. `note/` is Chinese.
- Do not introduce new dependencies or automation the user did not ask for.

## Workflow

Pick one track before writing anything, and say which one.

**Product / logic work** — data models, rules, backend, agents, tools, anything with a business rule:

```
OpenSpec change (what & why) -> plan -> TDD (red, then green) -> review -> verification -> archive
```

**Pure interface work** — pages and styling only. Logic is never "pure interface":

```
design in chat -> build -> verify in a real browser -> screenshots
```

Roles: OpenSpec owns *what* we build and the current-truth specs in `openspec/specs/`; proposed changes
live in `openspec/changes/`. Superpowers owns *how* we build it correctly. **The OpenSpec change is the
spec — do not write a second one.**

- Review: a fresh-context subagent, or the agent's own review command. Report only gaps affecting
  correctness or the stated requirements, not style.
- Verification: run `make verify` and show its output. Do not claim done without it.

## Agents and human gates

- **User** decides at key points (picks from proposed options and states why). **Claude Code** researches,
  proposes, writes the OpenSpec change and a scheduled plan, splits it into GitHub issues, dispatches,
  reviews, pushes, and opens PRs. **Codex** implements one issue per worktree with TDD and commits locally.
  **dsh** writes learning quizzes on merged work into `note/interview/`.
- Speed comes first. Two gates block and are always human: approving the design and merging a PR. Never
  automate them. Quizzes are asynchronous and never block development.
- Record every user decision with its reason in the OpenSpec change or `note/decisions.md`.
- Hand off through files and GitHub (issue -> PR -> review), never chat memory. The `dispatch` skill runs
  the loop; formats are in the guidelines, "Multi-agent collaboration".

## Reporting format

Every delivery report uses exactly these four sections, in this order, and nothing else.

**1. 你要做什么** · **2. 我完成了什么** · **3. 我遇到什么问题** · **4. 还没完成什么**

Rules:

- **Open every section with a one-line summary, then the detail.** For 我遇到什么问题 that means a plain
  label first — "遇到点 bug", "设计上有分歧", "环境问题", "没问题" — before any explanation.
- Lead with the user's action. Never open with a narration of what I did.
- One idea per line. No nested caveats inside a bullet.
- Report status per dimension separately: code, tests, CI, local run, deployment. Never merge a verified
  item with an unverified one in one sentence. Write "not run" or "not verified" plainly.
- Put reasoning, tradeoffs and history in `note/`, not in the report. Keep the report short.

## Git

- Follow [CONTRIBUTING.md](CONTRIBUTING.md) for branches, commits, and pull requests.
- Work on `<agent>/<topic>` branches and open a pull request into `main`. The user merges. Never push to
  `main`, force-push, or rewrite pushed history.
- `main` branch protection is a repository setting; the user enables it, not you.

## Session continuity

- At the start of a session, read `note/handoff.md` if it exists, and check it against `git status` and
  `git log` before trusting it.
- Before ending a session, or when asked for a handoff, overwrite `note/handoff.md`.

## Read before the relevant task

| Task | Sections in [agent guidelines](docs/engineering/agent-guidelines.md) |
| --- | --- |
| Resolving uncertainty, preparing factual content | Judgment and evidence |
| Importing content, assets, or profile data | Identity and privacy |
| Planning, implementing, or verifying a change | Scope and implementation; Verification and deployment |
| Git state, commits, pushes, pull requests | Git and changes; Identity and privacy |
| Deploying or releasing | Verification and deployment; Git and changes |
| Writing docs or reporting milestones | Communication and documentation |
| Dispatching, reviewing, or handing work between agents | Multi-agent collaboration; Git and changes |

## Project-specific

- **What this is:** OfferPilot — an application-planning agent for master's degrees at Australia's Group
  of Eight universities. The product is a visual application roadmap: open a phase and see what to
  prepare, when, and which official page the requirement came from.
- **Stack and commands:** Next.js + TypeScript in `web/`; FastAPI + PostgreSQL in `api/`. `make install`,
  `make dev`, `make verify` (the check command, same steps CI runs). `make help` lists everything.
- **Domain red lines:**
  - Never invent admission requirements, deadlines, thresholds, or sources. Every factual claim traces to
    an official page, or is marked `待核验`.
  - Never mark unverified data as verified. `verified_at` is set by a human, never defaulted.
  - Never render an unknown as an empty string or a zero; unknown stays unknown.
  - The advisor must not issue a judgement it cannot source.
- **Ask first before:** adding a dependency, changing the database schema, touching deployment or CI, or
  deleting files.
