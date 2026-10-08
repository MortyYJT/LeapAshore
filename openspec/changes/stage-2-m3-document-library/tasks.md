# 任务：阶段二 M3 材料库与审核依据

批次划分对应 `design.md` 的 D15：第 1–6 组是 PR 1（后端），第 7 组是 PR 2（前端），第 8 组是收尾。
每一组内的顺序按依赖排，标注 `TDD:` 的条目先写失败测试再写实现。

## 1. 依赖、配置与数据模型

- [x] 1.1 `api/pyproject.toml` 新增 `python-multipart` 依赖；`make api-install` 后确认 `UploadFile` 可解析（用户已批准，见 proposal）
- [x] 1.2 `Settings` 新增 `document_storage_root`，默认值由 `app/` 的位置推出（`<repo>/api/var/documents`）而不是依赖进程 cwd，并在 `.gitignore` 里忽略该目录
- [x] 1.3 新增 `api/app/models/document.py`：`documents`（client_id CASCADE、title、kind 可空、status、task_id SET NULL、program_id SET NULL 且 M3 恒为 NULL（D13）、current_version_id、archived_by/archived_at、created_at/updated_at）
- [x] 1.4 同文件新增 `document_versions`（`UNIQUE (document_id, version_no)`、document_id CASCADE、filename/mime_type/byte_size/sha256/storage_path/uploaded_by/created_at）。**这两张表互相引用，因此不声明任何 ORM relationship**：声明了就要么要 `foreign_keys`/`post_update`，要么让 SQLAlchemy 在删父行前把子行的 NOT NULL 外键置空（`api/app/models/roadmap.py:23-25` 记过这个坑）。不声明时 ORM 只发一条 DELETE，级联交给数据库的 CASCADE / SET NULL，查询一律显式 `select()`，与 `app/services/applications.py` 一致
- [x] 1.5 新增 `api/app/models/review.py`：`review_criteria`（code UNIQUE、scope、title、description、check_type、rule JSONB 可空、source_id NOT NULL RESTRICT、status、verified_at 可空、created_at/updated_at）
- [x] 1.6 同文件新增 `document_reviews`（document_id NOT NULL CASCADE、version_id NOT NULL CASCADE、overall CHECK、summary、reviewed_by、created_at）与 `document_review_findings`（review_id CASCADE、criterion_id NOT NULL RESTRICT、severity CHECK、finding、evidence_quote 可空且空引用写 NULL）
- [x] 1.7 在 `api/app/models/__init__.py` 里导出新模型：`alembic/env.py` 靠这个包看到全部表，漏了不会让测试变红，但下一次 `make revision` 会静默漏掉这五张表
- [x] 1.8 手写 `api/alembic/versions/*_add_document_library_and_review_criteria.py`：建 5 张表，`documents.current_version_id` 的外键用 `use_alter` 在两个表建好后补上（D7），`review_criteria` 的 `scope` 与 `check_type` 加 CHECK 约束，`downgrade` 按依赖倒序干净回退
- [x] 1.9 TDD: `api/tests/test_document_model.py` — 无 `source_id` 的要点被数据库拒绝；无 `criterion_id` 的建议被数据库拒绝；重复 `(document_id, version_no)` 被拒绝；越界的 `scope` / `check_type` / `severity` 被拒绝
- [x] 1.10 TDD: 同文件 — 引用了要点的来源不可删、引用了建议的要点不可删；删除 `clients` 时材料与版本级联消失（不报 NOT NULL 错）；删任务行时 `documents.task_id` 变 NULL 而材料仍在（D12）
- [x] 1.11 `make migrate` 从空库一次建全，`alembic downgrade -1` 再 `upgrade head` 干净往返

## 2. 上传、版本与下载（材料库后端）

- [x] 2.1 新增 `api/app/services/documents.py`：先按声明长度拒绝超限请求；搬运 spool 文件时按 64 KiB 分块并同时算 sha256 与字节数，超限即中止并清理已写入部分；空文件拒绝；按魔数判定类型（PDF/PNG/JPEG/DOCX，DOCX 再用 `zipfile` 确认 `word/document.xml`）
- [x] 2.2 同文件：内容寻址落盘（`blobs/<sha 前两位>/<sha>`），已存在则复用；新文件先写临时名再 `os.replace`；写库失败不回滚磁盘（D4 的孤儿 blob 是唯一失败模式）
- [x] 2.3 TDD: `api/tests/test_documents_api.py` — 声明超限与"谎报长度、实际超限"两种上传都返回 413，且存储根下没有留下文件；空文件 422
- [x] 2.4 TDD: 同文件 — 文本文件声明为 `application/pdf` 返回 415；不含 `word/document.xml` 的 zip 返回 415；PNG 声明为 `application/octet-stream` 入库为 `image/png`
- [x] 2.5 TDD: 同文件 — 相同字节上传两次只剩一个磁盘文件，两个版本行 `storage_path` 相同
- [x] 2.6 新增 `api/app/routers/documents.py`：`POST /api/documents`（首版）与 `POST /api/documents/{id}/versions`，字段名按 D16 固定（`file` 必填，`title` 与 `task_id` 选填，同一个路由不挂 JSON body），事务内首次上传同时写 document 与 version 1
- [x] 2.7 TDD: 同文件 — 跨主体读别人材料 404；`task_id` 指向别人的任务或指不到任何行都是 422 且不建材料；不带 `task_id` 的上传照存且 `task_id` 为 NULL；不带 `title` 时标题取文件名；并发抢同一个 `version_no` 时重试一次、仍失败为 409
- [x] 2.8 `GET /api/documents`（每个材料只带当前版本）与 `GET /api/documents/{id}`（完整版本列表，最新在前）：分类未定则 `kind` 为 `null`；没有结论时结论是空列表
- [x] 2.9 `GET /api/documents/{id}/versions/{n}/file`：`Content-Disposition: attachment` + RFC 5987 `filename*` + `X-Content-Type-Options: nosniff`；版本号不属于该材料则 404
- [x] 2.10 TDD: 同文件 — `DELETE /api/documents/{id}` 返回 405，材料、版本与文件都不变
- [x] 2.11 `app/main.py` 挂上 documents 路由

## 3. 归档与审核状态流转（材料库后端）

- [x] 3.1 `POST /api/documents/{id}/archive`：`kind` 必填且限于八个取值，写 `status=archived`、`archived_by`、`archived_at`；`under_review` 时一律 409，无论 `kind` 是否变化
- [x] 3.2 `POST /api/documents/{id}/submit`：要求 `kind` 已设且状态为 `archived` 或 `needs_revision`，置 `under_review`
- [x] 3.3 TDD: `api/tests/test_document_lifecycle.py` — 未归档就送审 409；`needs_revision` 可重送；`accepted` 无新版本重送 409；`under_review` 期间归档（含 `kind` 不变的情况）409；未知 `kind` 422；缺 `kind` 422
- [x] 3.4 TDD: 同文件 — 给 `accepted` 的材料上传新版本后状态回到 `uploaded`，`kind` 与 `archived_at` 不变（D5）

## 4. 审核依据（后端）

- [x] 4.1 新增 `api/app/seed_review_criteria.py`：录入 10 条 Genuine Student 骨架，复用 `seed_roadmap` 建的 GS 来源，`status="待核验"`，`verified_at` 一律不设（`check-no-fake-dates` 会扫这里）
- [x] 4.2 `seed_cli.py` 在路线图种子之后调用它；重复执行幂等
- [x] 4.3 `GET /api/review-criteria`：服务 code/scope/title/description/check_type/rule/status 与来源的 url/title/status，不解析 cookie
- [x] 4.4 TDD: `api/tests/test_review_criteria.py` — 每条都指向 GS 官网 URL；长度要点是 length 且 rule 为 `{"maxWords": 150}`；无机器可检规则的要点 `rule` 为 `null`；种子跑两次结果相同
- [x] 4.5 TDD: 同文件 — 读回来的要点全部 `待核验` 且 `verified_at` 为空；对要点路由发写方法返回 405
- [x] 4.6 TDD: 同文件 — 两个不同 cookie 读到相同的要点列表

## 5. 维护者 CLI（后端）

- [x] 5.1 新增 `api/review_cli.py`（argparse，风格对齐 `seed_cli.py`）：`verify-criterion <code>` / `unverify-criterion <code>`，写入 `now()`，是全仓库唯一写 `verified_at` 的地方
- [x] 5.2 同文件：`review <document_id> --version <n> --overall --reviewed-by --summary --finding "<code>:<severity>:<text>"`（可重复）；`--version` **必填**——审核结论描述的是具体字节，让操作者指名他看的是哪一版，才能在"审阅期间来了新版本"时拒绝而不是把结论挂到没人看过的文件上；`--finding` 按冒号切两刀（`split(":", 2)`），少于两个冒号即参数错误，`text` 里的冒号原样保留；一个事务内写 review + findings 并按结论推进材料状态
- [x] 5.3 TDD: `api/tests/test_review_cli.py` — verify 写入运行时间且状态变 `已核验`；unverify 清空日期
- [x] 5.4 TDD: 同文件 — `pass` + blocker 被拒；非 `pass` 且无 findings 被拒；severity 越界被拒；`reviewed_by` 为空被拒
- [x] 5.5 TDD: 同文件 — 要点 scope 与材料 kind 不匹配被拒（`general` 除外）；审核非当前版本 409；审核非 `under_review` 的材料 409
- [x] 5.6 TDD: 同文件 — `pass` 使材料变 `accepted`；`needs_revision` 变 `needs_revision`；`insufficient_evidence` 仍为 `under_review`
- [x] 5.7 `api/tests/conftest.py`：**改 `clear_the_roadmap_definition` 本身**（它才是删 GS 来源的那个函数，session 级 fixture 在第一个测试收集前就会调用它）——先删 findings、再删 criteria，然后才轮到 source；session 收尾在 `seed_roadmap` 之后接着调 `seed_review_criteria`，保持"跑完把开发库还原"的既有承诺
- [x] 5.8 TDD: 清扫相关 — 迁移到位后立即跑一次完整 `pytest`，确认 session 级清扫不再以 `review_criteria_source_id_fkey` 失败；删 `clients` 时材料、版本、结论、建议全部级联消失
- [x] 5.9 实测一次完整链路：CLI 写入一条带 `criterion_id` 的结论，`GET /api/documents/{id}` 能读到该建议引用的要点与官网 URL

## 6. PR 1 验收与提交

- [ ] 6.1 `make verify` 全绿，并把输出留在提交信息与 PR 描述里
- [ ] 6.2 独立审查（fresh-context subagent）：只报影响正确性或本 change 需求的问题
- [ ] 6.3 按审查结论修复，重跑 `make verify`
- [ ] 6.4 分支 `dsh/stage-2-m3-document-library-backend`，按 Conventional Commits 提交并开 PR 1（不合并，等用户）

## 7. 前端材料库（PR 2）

- [ ] 7.1 `web/lib/types.ts`：材料与版本的读取形状（列表只带当前版本，详情带完整版本列表且最新在前）、审核结论与建议（含要点与来源）的读取形状；`PhaseTask` 不动（`buildRoadmap` 不接触服务端 task 行）。要点来源的核验状态必须复用既有的归一化方向（未知一律读成 `待核验`，绝不读成 `已核验`，见 `programs-source.ts` 的 `toSourceStatus`）：把它提出来共用，而不是写第二份
- [ ] 7.2 `web/app/page.tsx`：由已有的 `taskRows` 建 `material_key → task id` 映射（与既有 `completedMaterialIds` 同源），并接上上传回调；映射不到任务时不拦上传，材料照存且 `task_id` 为空；补单测
- [ ] 7.3 `web/lib/api.ts`：读材料列表与详情、上传（multipart，字段名按 D16）、加版本、归档、送审、下载地址；上传失败要读出后端的中文错误而不是"上传失败"
- [ ] 7.4 新增 `web/components/MaterialsView.tsx`：材料列表（分类、状态、当前版本、时间），详情里展示版本列表、审核结论、逐条建议、引用的要点与官网链接，以及要点来源的核验状态
- [ ] 7.5 `web/components/AppShell.tsx` 增加"材料库"入口；`web/app/page.tsx` 接线（读服务端、写入后重读，与既有的档案/组合写法一致）
- [ ] 7.6 `web/components/FlowView.tsx` 任务行加上传入口，回调只传 `materialId`，任务 id 由 `page.tsx` 解析
- [ ] 7.7 前端单测：适配层对照抓下来的真实响应 fixture；未归档材料的 `kind` 渲染为"未分类"而不是"其他"
- [ ] 7.8 `scripts/e2e-walkthrough.cjs` 增加步骤：任务行上传一个真实 PDF → 材料库看到它 → 归档 → 送审 → 重新加载后状态仍在；截图写入 `docs/screenshots/`
- [ ] 7.9 `make verify` 全绿（含浏览器走查截图），仍按 §4 报告格式给证据
- [ ] 7.10 独立审查 + 修复；分支 `dsh/stage-2-m3-document-library-frontend`，开 PR 2（不合并，等用户）

## 8. 收尾

- [ ] 8.1 重写 `note/handoff.md`：日期、分支与提交、change id、已完成与证据、未完成、下一步、坑
- [ ] 8.2 `note/product/roadmap.md` 把 M3 标为已完成并填上 change id；`note/product/backlog.md` 记下本批次暴露的新想法
- [ ] 8.3 两个 PR 都合入后，`openspec archive stage-2-m3-document-library`，把 spec 归档进 `openspec/specs/`
