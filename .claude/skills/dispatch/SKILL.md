---
name: dispatch
description: Use when an approved OpenSpec change and scheduled plan exist and work should be handed to Codex, reviewed, turned into a PR, and queued for an async dsh quiz. Runs the multi-agent loop from AGENTS.md without automating the two blocking human gates (design approval, merge).
---

# Dispatch loop (Claude Code as coordinator)

Read `AGENTS.md` ("Agents and human gates") and the guidelines section "Multi-agent collaboration" first. Never automate gate 1 (design approval) or gate 2 (merge). Learning quizzes are queued, never awaited.

## Preconditions

- The user approved the design (gate 1) in this session or in `note/handoff.md`, and the OpenSpec change id is known.
- `gh auth status` succeeds, and `codex` and `dsh` are on PATH. If one is missing, stop and tell the user.

## Steps

1. **Issues.** For each group of related plan steps, open an issue with `.github/ISSUE_TEMPLATE/task.md` (`gh issue create --template task.md ...`). Fill in scope and the `TODO(human)` parts.
2. **Worktree.** Run `git fetch origin`, then `git worktree add ../<repo>-<topic> -b codex/<topic> origin/main`.
3. **Dispatch.** `codex exec --cd ../<repo>-<topic> --sandbox workspace-write -o <scratch>/codex-<issue>.md "<issue body> Follow AGENTS.md. Use TDD. Make one commit per plan step. Leave TODO(human) parts unimplemented. Do not push. End with a report: files changed, tests run with results, open questions."` Verify the flags with `codex exec --help` for the installed version.
4. **Check the delivery yourself.** In the worktree, run `make verify` (needs the dev database up; `make api-test` alone is not enough), read the diff against the issue's scope, and confirm the commits. Do not trust the report alone.
5. **Review.** Use a fresh-context review (a subagent or the review command), limited to correctness and requirement gaps.
   - Changes needed: send the findings back with `codex exec resume --last` (or a new `codex exec` in the same worktree). At most two rounds; then stop and hand over to the user.
   - Ready: push the branch (your guard hook applies), then `gh pr create` using the PR template, with `Closes #N`. Post the review summary as a PR comment.
6. **Gate 2.** Tell the user the PR is ready and wait. Do not merge.
7. **Queue a quiz (after the user merges; non-blocking).** In the **main checkout** (not a separate worktree), switch to a new branch `dsh/quiz-<pr>` from the updated `main`, then run `dsh headless "Read PR #<n> and the changed files. Write note/interview/<pr>.md: a short plain-Chinese summary of what was built and why, then six questions (three on design, three on code reading) with empty answer slots. Do not change any other file."` dsh keys sessions by working directory (`~/.dsh/sessions/<encoded-path>/`), so running from the main checkout makes this one new conversation listed under the project in the DeepSeek Harness app (verified 2026-10-10), where the user continues learning. Record the newest session id from that folder at the top of the file. Check that only the quiz file changed, commit it for a docs PR, tell the user in one line that it is queued, and continue with the next issue. Do not wait. Requires `DEEPSEEK_API_KEY` in the environment (the headless profile does not see the app's managed key); never print it.
8. **When the user answers (any time).** Mark each answer ✅/⚠️/❌ and add misses to the review list in the same file.
9. **Handoff.** Update `note/handoff.md`: issues and PRs in flight, the last verified state, and the next step.

## Record for the resume

Keep counts in `note/handoff.md` or the stage log: issues dispatched, PRs merged, review findings, rework rounds, and dispatch-to-merge time. These are the evidence behind any "multi-agent workflow" claim.
