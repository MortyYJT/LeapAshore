# Stage 2 M3 backend verification

Date: 2026-10-08 (Australia/Melbourne)
Scope: `api/` — the material library, the review criteria and the operator command
OpenSpec change: `stage-2-m3-document-library` (tasks.md groups 1–6)
Verified by: parent agent, executed on the local machine

Status is reported per dimension. Anything not exercised is marked as not verified.

## 1. Build

Command: `make build` (that is `cd web && NEXT_DIST_DIR=.next-build npm run build`)

Result: **passed**

```
▲ Next.js 16.2.11 (Turbopack)
✓ Compiled successfully in 823ms
  Running TypeScript ...
  Finished TypeScript in 1013ms ...
✓ Generating static pages using 4 workers (3/3) in 128ms
```

TypeScript runs in strict mode; there are no type errors. This batch changes no front-end source, so
the build is a regression check rather than new evidence.

## 2. Guards

| Command | Result |
| --- | --- |
| `node scripts/check-no-fake-dates.cjs` | `未发现硬编码的核验日期` |
| `node scripts/verify-programs-mirror.cjs` | 6 programs match `web/lib/programs.ts` field by field |
| `node scripts/check-no-programs-import.cjs` | passed |
| `node scripts/verify-roadmap-mirror.cjs` | passed |

The date guard is the one this batch had to be written around: the criteria seed and the operator
command are the two places a verification date could appear, and the command is the only writer of
`verified_at` anywhere, stamping the moment it runs rather than any written-out date.

## 3. Backend tests

Command: `make api-test` (that is `cd api && .venv/bin/pytest -q`)

Result: **195 passed**

```
195 passed, 1 warning in 4.54s
```

106 tests existed before this batch and 89 are new: the model constraints (12), the upload service
(15), the HTTP routes (14), the middleware (5), the lifecycle transitions (12), the criteria seed and
route (12), the operator command (19).

The suite was run twice in a row on the same database. That is the check that matters most here: the
session sweep deletes the roadmap definition and the Genuine Student source before the first test is
collected, `review_criteria.source_id` is RESTRICT, and the teardown has to put back both the
definition and whatever a person had verified. One run that left the database different would make the
next one fail for a reason unrelated to what it tests.

## 4. End-to-end walkthrough

Command: `make screenshots` (that is `node scripts/e2e-walkthrough.cjs`)

Result: **25 screenshots produced**, every check reported `是`, no JavaScript errors

```
本次走查创建的主体数: 4
走查结束时清理了本次主体（组合行与主体行）: 是 {"subjects":4,"removedApplications":"6","removedClients":"2","leftOver":"0","clientsLeft":"0"}
=== JS 错误 ===
无
```

The two `console: ... status of 500` lines this run prints are the walkthrough's own injected
failures (it forces a profile save and a portfolio save to fail on purpose to check that the page says
so). They are listed under "本次走查有意注入的错误".

The walkthrough covers no material upload: this batch adds no interface for it. That is the next
batch, and until then the upload path is verified by the tests above and by the operator-command
exercise below rather than in a browser. **Not verified in a browser.**

## 5. Deployment

**Not run.** This batch changes no deployment configuration. The known limits are recorded in the
change's design (Open Questions 1): the storage root is a local directory, and the deployed front end
sits behind Vercel, whose serverless request body cap is roughly 4.5 MB — so the 20 MiB upload cannot
reach the backend there at all. M3 does not claim otherwise.

## 6. Known limits

- **The upload has never been served from a deployed environment**, for the reason above.
- **`api/var/documents` is the only place files live.** `alembic downgrade -1` drops the five tables
  and leaves those files on disk; nothing points at them afterwards, and this batch deletes nothing.
- **One pre-existing leak remains**: `api/tests/test_sources.py::test_source_url_is_unique` leaves one
  `sources` row behind per run. It is recorded in `note/product/backlog.md` and is not introduced here;
  measured before and after a single run, the row count rises by exactly that one row.
