@AGENTS.md

## Claude Code specifics

- **Only the guard hook is installed** (`.claude/hooks/guard.sh`, PreToolUse). It blocks writes to secret
  files, push to `main`, force-push, `git reset --hard`, and broad `rm -rf`. The `verify.sh` Stop hook is
  deliberately not installed, because `make verify` needs the database and runs screenshots; run it
  yourself before claiming work is done.
- The project's check command is `make verify`. Run it before claiming work is done.
- Use plan mode when the approach is uncertain, the change touches several files, or it is an OpenSpec
  change. If the diff can be described in one sentence, skip the plan and just do it.
- When compacting, always preserve the list of modified files, the current OpenSpec change id, and the
  check command. Before a long session ends or context gets heavy, update `note/handoff.md`.
