# 第二阶段 M2c（选校组合落库）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 选校组合从浏览器存储搬到服务端，并让前端从 `/api/programs` 取项目数据而不是读代码里的常量。

**Architecture:** 新增 `applications` 表（每用户每项目一行，带 `origin` 与唯一的"首选"约束）。前端 `PortfolioPicker` 改为读写接口；`web/lib/store.ts` 的 `portfolio` 退役。项目数据由 M2a 已上线的 `/api/programs` 提供，适配层处理 M2a 记录在接口文档里的两处差异（`name ← nameEn`、5 个字段的可空性）。

**Tech Stack:** 同前，无新依赖。

**Spec:** `note/superpowers/specs/2026-10-06-stage-2-m2-design.md` §3.2、§3.6、§4.1、§8.4、§8.5

## Global Constraints

- 源码注释、docstring、工程文档英文；`note/` 中文例外；UI 文案与测试字符串中文。
- Conventional Commits 1.0.0，**必须有 scope**，**必须有非空英文 body**，body 每条 `- ` 开头。
- 不改写已推送历史，不 force-push。提交前 `git diff --cached --check`。
- **不引入新依赖。**
- 不提交 `api/.env`、`api/.venv`、`web/.next*`、`.runtime-tools/`、`__pycache__`。
- 分支：`codex/stage-2-m2c-applications`。
- **每个用户至多一个 `is_primary = true`** —— 用**部分唯一索引**在数据库层保证，不能只靠代码。
- 跨主体读写必须被拒绝，且测试要**证明申请方的 cookie 被读过**（送上另一主体的行 id，断言 404 而非 200）。
- 每次改动写一条 `task_events`。
- **不得凭空补项目数据。** `/api/programs` 是唯一来源；前端不再以 `web/lib/programs.ts` 为数据源。

---

### Task 1: `applications` 表

**Files:** Create `api/app/models/application.py`；Modify `api/app/models/__init__.py`；Create migration；Create `api/tests/test_application_model.py`

**Interfaces:** Produces `app.models.application.Application`、`ApplicationOrigin`；从 `app.models` 再导出。

- [ ] **Step 1: 写失败测试** —— 覆盖：默认 `origin` 为 `user`；`UNIQUE (client_id, program_id)`；**部分唯一索引让同一主体不能有两个 `is_primary`**（断言 `IntegrityError`）；删主体级联删行；`official_deadline` 与 `deadline_source_url` 可空且默认 `None`。
- [ ] **Step 2: 跑测试确认失败**（`ModuleNotFoundError`）
- [ ] **Step 3: 写模型** —— 字段：`id`、`client_id` FK CASCADE、`program_id` FK programs、`tier`、`status`、`is_primary`、`official_deadline`、`deadline_source_url`、`needs_review`、`origin`（默认 `user`）、时间戳。`__table_args__` 里加 `UniqueConstraint("client_id","program_id")` 与 `Index(..., unique=True, postgresql_where=text("is_primary"))`。
- [ ] **Step 4: 生成迁移并人工校对** —— 特别确认**部分唯一索引真的生成了 `postgresql_where`**，否则约束是假的。
- [ ] **Step 5: 升降级验证**
- [ ] **Step 6: 跑测试 + `make test`**
- [ ] **Step 7: 提交**

---

### Task 2: 组合的读写接口

**Files:** Create `api/app/schemas/application.py`、`api/app/routers/applications.py`；Modify `api/app/main.py`、`api/app/services/roadmap_tasks.py`（复用写事件的辅助）；Create `api/tests/test_applications_api.py`

**Interfaces:** Produces `GET /api/applications`、`PUT /api/applications`；`app.services.applications.replace_applications(session, client_id, rows) -> dict`

- [ ] **Step 1: 写失败测试** —— 覆盖：空组合返回 `[]`；`PUT` 整体替换并回读；**同一主体两个 `is_primary` 被拒（422 而非 500）**；`PUT` 到另一个主体的组合不影响第一方；`GET` 只返回本主体的行（**并断言 cookie 被读过**）；每次改动写 `task_events`（`actor="user"`）。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** —— `PUT` 接受整份组合，删除不再出现的行、更新已有行、插入新行，全部在一个事务里；把 `is_primary` 冲突映射成 422 并指名；未知 `program_id` 映射成 422。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交**

---

### Task 3: 前端从接口取项目并读写组合

**Files:** Modify `web/lib/api.ts`、`web/components/PortfolioPicker.tsx`、`web/lib/store.ts`、`web/app/page.tsx`；Create `web/lib/programs-source.ts`、`web/lib/programs-source.test.ts`；Modify `scripts/e2e-walkthrough.cjs`

**Interfaces:** Produces `fetchPrograms()`、`fetchApplications()`、`replaceApplications(rows)`；`toProgramView(served)` 纯函数

- [ ] **Step 1: 写失败测试** —— 纯函数 `toProgramView`：`name ← nameEn`（M2a 的接口文档已记录该映射）；5 个字段的可空性修正——`null` 渲染成"未知"而**不是空字符串**；断言字段名与一个**从真实接口抓取的响应快照**一致（`web/lib/roadmap-response.fixture.json` 的先例：不要让 fixture 与适配器互相印证）。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现适配层与接口函数**
- [ ] **Step 4: 接线 `PortfolioPicker`** —— 项目来自接口；`web/lib/store.ts` 的 `portfolio` 退役（**保留键不删**，照 `completedMaterials` 的先例，避免破坏既有断言）；确认流程改为 `PUT`。
- [ ] **Step 5: 走查断言** —— 加一条**能失败**的：清空浏览器存储后重载，组合仍在，且与服务器一致。
- [ ] **Step 6: 跑全量** `make test && make build && make screenshots`
- [ ] **Step 7: 提交**

---

## 自检

| spec 要求 | 任务 |
|---|---|
| §3.2 `origin` | Task 1 |
| §3.6 至多一个首选（数据库层） | Task 1、2 |
| §4.1 `applications` | Task 1 |
| §5 `GET`/`PUT /api/applications` | Task 2 |
| §8.4 至多一个 `is_primary` | Task 1、2 |
| §8.5 跨主体拒绝且证明 cookie 被读 | Task 2 |
| §8.6 前端组件不改 | Task 3（只改数据来源） |
| `/api/programs` 接上（M2d 提前到此） | Task 3 |

**风险**：部分唯一索引若 autogenerate 不生成 `postgresql_where`，约束是**假的**——Task 1 Step 4 必须查 `pg_indexes` 确认。这是本批最容易被静默放过的地方。

## 执行方式

Subagent-Driven，4 个任务分批。
