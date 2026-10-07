# Repository instructions

- Follow the language, commit-message, and Git rules in CONTRIBUTING.md.
- Keep source comments, docstrings, and engineering documentation in English. Chinese planning and learning records belong in note/; preserve Chinese runtime and test strings such as UI copy, prompts, public errors, and test examples.
- Use codex/ branches and pull requests into main. The user merges manually. Do not push directly to main or rewrite already-pushed history.
- For code tasks, `gpt-6-luna` with `max` reasoning is the primary implementer and the parent agent owns primary acceptance. If implementation quality is insufficient, the parent may take over and record the reason.
- For an explicitly authorized Vibe-coding exception, follow the user's stated exception without adding brainstorm, TDD, or code-review gates that the user waived.
- Do not introduce new approval steps, dependencies, or complex automation unless the user asks for them.

## 1. Workflow

Two tracks. Pick one before writing anything, and say which one out loud.

**Product and logic work** — full flow, no skipping:

```
brainstorm → spec → plan → TDD (red, then green) → review → verification
```

This covers data models, rules, the backend, the agent, tools, and anything with a business rule.

**Pure interface work** — the user has accepted real-browser verification as the acceptance record
for pages and styling, in place of the tests above:

```
design in chat → build → verify in a real browser → screenshots
```

Do not extend this exception to logic. A rule, a calculation or a data shape is product work even
when it renders on a page.

## 2. Reporting format

Every delivery report uses exactly these four sections, in this order, and nothing else.

**1. 你要做什么** — the single action required from the user, or "nothing".

**2. 我完成了什么** — one line per finished item, each with its evidence.

**3. 我遇到什么问题** — what went wrong or blocked, and how it was resolved.

**4. 还没完成什么** — what is unfinished or unverified.

Rules:

- **Open every section with a one-line summary, then the detail.** The user reads the summary to
  decide whether the detail concerns them. For 我遇到什么问题 that means a plain label first —
  "遇到点 bug", "设计上有分歧", "环境问题", "没问题" — before any explanation. For 我完成了什么 it
  means one sentence naming what now works, before the itemised list.
- Lead with the user's action. Never open with a narration of what I did.
- One idea per line. No nested caveats inside a bullet.
- Report status per dimension separately: code, tests, CI, local run, deployment. Never merge a
  verified item and an unverified one into a single sentence.
- Write "not run" or "not verified" plainly. Do not write "should be fine".
- Put reasoning, tradeoffs and history in note/, not in the report.
- Keep the report short. If it needs a table, the table has at most four columns.

## 3. Repository state

- The previous implementation is kept as an ancestor of the rebuild. Its commits stay in history;
  its code is not carried forward.
- New work goes on a `codex/` branch, pushed, then opened as a pull request with `gh` and merged by
  the user.
- The GitHub CLI is installed at `.runtime-tools/`, which is ignored by Git. Authenticate it from the
  stored Git credential rather than asking the user for a token, and never print a token.
