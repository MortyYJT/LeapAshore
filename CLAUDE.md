@AGENTS.md

## Claude Code specifics

- **The hooks are not installed in this repository.** `guard.sh` and `verify.sh` were deliberately
  skipped, so the prohibitions they enforce — no writes to secret files, no push to `main`, no
  force-push, no `git reset --hard`, no broad `rm -rf` — are rules only, with nothing blocking you.
  Treat them as strictly as if a hook did.
- The project's check command is `make verify`. Run it before claiming work is done.
- Use plan mode when the approach is uncertain, the change touches several files, or it is an OpenSpec
  change. If the diff can be described in one sentence, skip the plan and just do it.
- When compacting, always preserve the list of modified files, the current OpenSpec change id, and the
  check command. Before a long session ends or context gets heavy, update `note/handoff.md`.
