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

## 7. Requirement coverage across both batches

Every requirement in the change's three specs, with the code that implements it and the check that
would fail if the behaviour were removed. The two reviewers walked this list independently for their
own batch; this is the consolidated version, and it exists so a reader of the pull requests can see
that nothing in the specs is unimplemented rather than take that on trust.

| Capability | Requirement | Code | Check |
| --- | --- | --- | --- |
| document-library | A document belongs to exactly one subject | `api/app/routers/documents.py:53` (`_own_document`), every route | `test_documents_api.py` — "another subject cannot read the detail", "…cannot download the file"; walkthrough's cross-subject probes |
| | Every document has at least one immutable version | `api/app/services/documents.py:store_upload`, `add_version` | `test_documents_service.py` — "a second upload appends a version" |
| | An upload is bounded in size | `services/documents.py:_stage`, `app/middleware.py` | `test_documents_service.py` — "an oversized upload is refused and leaves nothing"; `test_middleware.py` — "a declared oversize body never reaches the app" |
| | An upload's type is decided by its bytes | `services/documents.py:detect_mime` | `test_documents_service.py` — "a text file claiming to be a pdf is refused", "a zip that is not a word document"; walkthrough — "服务端按魔数判定了类型…" |
| | Identical bytes are stored once | `services/documents.py:blob_relpath`, `_place` | `test_documents_service.py` — "the same bytes are stored once"; "a truncated blob is repaired" |
| | The file content lives outside the database | `models/document.py:storage_path`, `config.py` | `test_documents_service.py` — "the stored path is relative and the file is there" |
| | Archiving classifies a document | `services/documents.py:archive_document` | `test_document_lifecycle.py` — archiving, missing kind, unknown kind, under-review refusals; walkthrough — 归档 |
| | A document moves through a defined set of review states | `services/documents.py:ARCHIVE_ALLOWED_FROM`, `SUBMIT_ALLOWED_FROM` | `test_document_lifecycle.py` (12 cases); `test_review_cli.py` for the verdict transitions |
| | An upload names the file and may name a requirement | `routers/documents.py:upload_document` | `test_documents_api.py` — task outcomes; walkthrough — "上传时挂上了这条材料对应的任务要求" |
| | The applicant can read their own material library | `routers/documents.py:read_documents`, `read_document` | `test_documents_api.py` — list/detail shapes; `materials-source.test.ts` against captured bodies |
| | A stored file can be downloaded and cannot be rendered as a page | `routers/documents.py:download_version` | `test_documents_api.py` — attachment, `nosniff`, filename, containment; walkthrough — "下载拿到的是存进去的那份文件" |
| | This change removes nothing | no delete route; `test_documents_api.py` asserts 405 | `test_documents_api.py` — delete and PUT refusals; `test_middleware.py`; the reviewers' live method sweep |
| | The material library is usable from the interface | `components/MaterialsView.tsx`, `FlowView.tsx`, `app/page.tsx` | the whole walkthrough block: upload, classify, submit, download, reload |
| document-review | A review names the exact version it judged | `services/reviews.py:record_review`, `version_no` | `test_review_cli.py` — "a superseded version cannot be reviewed" |
| | Every finding cites a review criterion | `models/review.py` NOT NULL, `services/reviews.py:_resolve_findings` | `test_document_model.py` — "a finding without a criterion is refused" |
| | A finding's criterion must apply to the material it judges | `services/reviews.py` scope check | `test_review_cli.py` — "a criterion from another scope is refused", "a general criterion applies to any material" |
| | A review cannot contradict itself | `services/reviews.py` pass/blocker and non-pass/empty checks | `test_review_cli.py` — those two refusals |
| | Recording a review moves the material's state | `services/reviews.py:SETTLED_BY_OVERALL` | `test_review_cli.py` — accepted, needs_revision, insufficient_evidence |
| | A review says who made it | `services/reviews.py:EMPTY_REVIEWER` | `test_review_cli.py` — "a review without an attribution is refused" |
| | The owner can read the reviews of their own document | `routers/documents.py:_reviews`, `read_reviews` | `test_documents_api.py` — reviews for the owner, 404 for others; `test_review_cli.py` — "the recorded review reaches the applicant with its source"; walkthrough — the rendered panel |
| | Reviews are recorded by a human operator, not over HTTP | `review_cli.py`; `routers/documents.py` declares only GET on `/{id}/reviews` | `test_review_cli.py`; `test_documents_api.py` — the 405s |
| review-criteria | A review criterion must cite an official source | `models/review.py` NOT NULL + RESTRICT | `test_document_model.py` — "a criterion without a source is refused", "a cited source cannot be deleted" |
| | A criterion's verification state is set by a human and never defaulted | `services/reviews.py:verify_criterion` (the only writer) | `test_review_cli.py` — verify, unverify, unknown code; `test_review_criteria.py` — seeded rows are 待核验; `check-no-fake-dates.cjs` |
| | The seeded criteria trace to the Genuine Student requirement page | `app/seed_review_criteria.py` | `test_review_criteria.py` — every citation is that url, the seed is repeatable, and it keeps a human's verification |
| | A criterion states only what it can be checked against | `models/review.py` CHECKs, `rule` nullable | `test_document_model.py` — scope and check-type refusals; `test_review_criteria.py` — the 150-word rule, `rule: null` elsewhere |
| | Criteria are readable with the page they came from | `routers/review_criteria.py` | `test_review_criteria.py` — the served list, no cookie needed, 405 for writes |

The archive was rehearsed in a throwaway copy of the repository before this document was written:
`openspec archive stage-2-m3-document-library` reports `{"added": 26, "modified": 0, "removed": 0,
"renamed": 0}`, moves the change to `openspec/changes/archive/2026-10-08-stage-2-m3-document-library/`,
and writes the three current-truth specs to `openspec/specs/<capability>/spec.md`. It is run after both
pull requests are merged, not before.
