# Contributing

## Language

Write source comments, docstrings, the README, contribution guides, and engineering documentation in
English. Chinese planning and learning records belong in `note/`.

Keep Chinese text when it is runtime or test data: interface copy, brand names, prompts shown to users,
public error messages, and test inputs or outputs. Do not translate those strings as part of documentation
cleanup.

- `note/` — Chinese planning, design records, learning logs, and implementation plans.
- `docs/` — English engineering documentation and verification reports.

## Commits

Follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/). The standard permits
an omitted scope and an omitted body. This repository adds two mandatory requirements: every commit must
include a scope and a non-empty English body.

```
<type>(<scope>): <subject>

- what changed and why, one line per item
- what was verified, and how
```

Each body item starts with `- `. A wrapped continuation line is indented, not a new item.

## Branches and pull requests

- Branch from an up-to-date `main` as `<owner>/<topic>`, where `<owner>` is the agent that did the work
  (`codex/`, `claude/`, `dsh/`, …) or `me/` for your own. New agents take their own prefix; do not reuse
  another agent's. Use short kebab-case topics, e.g. `codex/stage-2-m2a-roadmap-definition`.
- Open a pull request into `main`. The user merges; do not merge your own work.
- Never push to `main`, force-push, or rewrite already-pushed history.
- Run `git diff --cached --check` before each commit.

## Verification

Evidence over assertion. A pull request states what it changed, what it verified, and how. The check
command is `make verify`; CI runs the same steps.

## Repository hygiene

Keep `.env`, `.venv`, `.runtime-tools/`, build output, and scratch directories out of the repository. They
are ignored; do not commit them, and do not commit a file you had to force.
