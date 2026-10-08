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

Result: **200 passed**

```
200 passed, 1 warning in 4.79s
```

106 tests existed before this batch and 94 are new: the model constraints (12), the upload service
(17), the HTTP routes (16), the middleware (5), the lifecycle transitions (12), the criteria seed and
route (13), the operator command (19).

The suite was run twice in a row on the same database. That is the check that matters most here: the
session sweep deletes the roadmap definition and the Genuine Student source before the first test is
collected, `review_criteria.source_id` is RESTRICT, and the teardown has to put back both the
definition and whatever a person had verified. One run that left the database different would make the
next one fail for a reason unrelated to what it tests.

### An intermittent failure, and why it is not this batch's

The suite is **not deterministic**, and that had to be established rather than assumed. During this
session the full suite failed intermittently: three runs reported 14, 3 and 12 failures while the rest
reported 196 passed. The symptoms are always the same shape — a row a test depends on is gone while it
still needs it:

```
applications_client_id_fkey: Key (client_id)=… is not present in table "clients"
applications_program_id_fkey: Key (program_id)=(test-applications-program-reach) is not present
documents_client_id_fkey:    Key (client_id)=… is not present in table "clients"
duplicate key value violates unique constraint "roadmap_phases_pkey"
```

`test_applications_api.py` alone reproduces it, so it is not cross-module pollution from the new
modules. The decisive check was an A/B, with this batch's code absent: a worktree at `main`, the M3
tables dropped, `tests/test_applications_api.py` run six times with main's own code —

```
15 passed | 3 failed, 12 passed | 6 failed, 9 passed | 15 passed | 15 passed | 15 passed
```

Two of six runs failed on unchanged code, so this is **pre-existing** and is recorded in
`note/product/backlog.md` for its own investigation. The likely area is the interaction between
`conftest`'s sweeps and the module-scoped probe fixtures (the probe catalogue
`test_applications_model.py` writes for its own module), not this batch's tables.

After restoring the schema, `make api-test` passed **twelve consecutive times**. The count below is
what a passing run reports; it is not a claim of determinism.

### The independent review round

A fresh-context reviewer read the specs, the design, the whole diff and the code it touches, ran the
tests, probed every declared path and method on a live API, and exercised the multipart parser and
Starlette's `FileResponse` directly. It found no gap in isolation, provenance, path handling or the
state machine, and it named these, all of which are now fixed:

| Finding | What changed |
| --- | --- |
| The version number was chosen without a lock, so two uploads for one material could interleave | `_next_version_no` takes a row lock on the material; the number is chosen once and the retry reuses it rather than recomputing one |
| The spec's own version-number race had no test | Two threads upload to one material at once and assert the numbers are exactly 1, 2, 3; measured failing without the lock |
| An existing blob was reused without being checked, so a truncated one would serve wrong bytes under a correct digest | `_place` compares the file's length and repairs a mismatch |
| A missing source was served as `""` for url, title and status, where the rule is null | `SourceRef`'s three fields are nullable and the routers pass null |
| `test_a_check_type_outside_the_set_is_refused` could pass for another reason | Every insert-and-refuse test now asserts *which* constraint refused it, by name |
| `PUT /api/documents/{id}` had no test | Added, asserting 405 and that the row is unchanged |

The reviewer independently reproduced the intermittent failure above on `main`, which is the second
confirmation that it predates this batch.

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
