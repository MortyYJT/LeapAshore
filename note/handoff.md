# Session handoff

**This is the only current-state file. Overwrite it at the end of a session; read it at the start.**
Verify it against `git status` and `git log` before trusting it.

## Where we are

- Branch: `codex/bootstrap-agent-rules` (not yet committed or pushed).
- `main` carries stage 1 plus stage 2's M1 and M2 groups (M2a–M2d), merged as PRs #1–#6. 7 migrations,
  106 backend tests, 150 frontend tests, 4 Node guards.
- Live site: https://web-gamma-sepia-86.vercel.app

## What this session did

Installed the general AI-development template: `AGENTS.md` and `CONTRIBUTING.md` merged, `CLAUDE.md`,
`docs/engineering/agent-guidelines.md`, `.github/pull_request_template.md`, `note/product/*`, and
`note/handoff.md` added. OpenSpec initialised (`openspec/config.yaml`); `.claude/` and `.codex/` hold its
skills and commands. **The template's hooks were deliberately not installed** — the prohibitions they
enforce are rules only.

## Next

Stage 2's M3: the document library (upload, versions, archiving) and review criteria with official
sources, so the Genuine Student review work has somewhere to land. Start it as an OpenSpec change.

## Check command

`make verify` — build, tests and the browser walkthrough. CI runs the same steps.

## Open items

- `main` branch protection is not enabled on GitHub; only the user can turn it on.
- Several deferred minors are recorded per-batch in `.superpowers/sdd/*/progress.md`.
