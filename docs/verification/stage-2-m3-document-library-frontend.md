# Stage 2 M3 front-end verification

Date: 2026-10-08 (Australia/Melbourne)
Scope: `web/` — the material library view, the task-row upload, and the walkthrough steps
OpenSpec change: `stage-2-m3-document-library` (tasks.md group 7)

Status is reported per dimension. Anything not exercised is marked as not verified.

## 1. Build

Command: `make build` (that is `cd web && NEXT_DIST_DIR=.next-build npm run build`)

Result: **passed**

```
✓ Compiled successfully in 868ms
  Running TypeScript ...
  Finished TypeScript in ...
✓ Generating static pages using 4 workers (3/3)
```

## 2. Guards

| Command | Result |
| --- | --- |
| `node scripts/check-no-fake-dates.cjs` | `未发现硬编码的核验日期` |
| `node scripts/verify-programs-mirror.cjs` | 6 programs match `web/lib/programs.ts` field by field |
| `node scripts/check-no-programs-import.cjs` | passed |
| `node scripts/verify-roadmap-mirror.cjs` | passed |

## 3. Tests

| Suite | Result |
| --- | --- |
| Front end (`node --test lib/*.test.ts`) | **172 passed** — 150 before this change, 22 new |
| Back end (`cd api && pytest -q`) | **200 passed** — unchanged by this batch |

The 22 new front-end tests are the library adapter (12) and the transport (10). The adapter's are bound
to two bodies captured from the running server — `materials-list.fixture.json` and
`materials-detail.fixture.json`, the second carrying a review whose finding cites the official page —
because an adapter tested against a body written from its own declarations agrees with itself. That is
how `roadmap-source.ts` once read `id`/`label` while the wire said `key`/`title` with every test green.

## 4. End-to-end walkthrough

Command: `make screenshots` (that is `node scripts/e2e-walkthrough.cjs`)

Result: **28 screenshots**, every check `是`, no JavaScript errors, exit code 0

Three screenshots are new — `26-material-uploaded`, `27-material-submitted`,
`28-material-survives-reload` — and the block added for this batch reports:

```
上传材料发出了一条真实的 POST /api/documents: 是 {"uploads":1}
服务端自己持有刚上传的材料: 是 {"rows":1}
服务端按魔数判定了类型，而不是信客户端声明: 是 {"mimeType":"application/pdf"}
上传时没有分类，服务端如实记为空: 是 {"kind":null}
材料库渲染了这份材料: 是 {"rows":1}
未分类的材料显示为未分类，而不是其他材料: 是 {"badges":"未分类 / 待归档"}
归档写进了服务端，并记下了分类与归档时间: 是 {"kind":"transcript","status":"archived"}
送审把材料推进到审核中: 是 {"status":"under_review"}
打开审核面板读的是详情接口: 是 {}
还没有审核结论时，面板说的是还没有，而不是编一条出来: 是
刷新后材料、分类与状态仍在（全部来自服务端）: 是
```

Every other screenshot was regenerated: the tab row gained a fourth entry, so every shot that shows the
header changed. The diff therefore contains all of them rather than only the three new ones.

## 5. What the browser cannot cover

- **Writing a review has no browser path**, by design: recording one is the operator command
  (`api/review_cli.py`) and there is no HTTP route for it. The walkthrough can only assert that a
  material nobody has reviewed says so, which it does. The review *rendering* path — a finding with its
  criterion and its official page — is covered against the captured detail body in
  `materials-source.test.ts`, not in a browser. **The rendered review panel has not been seen in a
  browser.**
- **Nothing is deployed.** The deployed front end sits behind Vercel, whose serverless body cap is about
  4.5 MB, so a 20 MiB upload cannot reach the backend there at all; the storage root is also a local
  directory. M3 claims nothing about the deployed environment.

## 6. Known limits

- The walkthrough's cleanup removes the subject and the material rows through the foreign key cascade,
  but the uploaded file stays under `api/var/documents`: this batch deletes no files, by design (design
  D11). Three such files were left by the runs above. They are inside a git-ignored directory.
- The suite remains intermittently red against the shared development database, as
  `stage-2-m3-document-library-backend.md` §3 records with its A/B. It reproduces on `main` with this
  batch's code absent and is not introduced here. `make verify` passed on the run above.
