# 第二阶段 M2d（视图改用服务端目录）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: use subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 让 `HomeView` 与 `FlowView` 不再用代码里的 `PROGRAMS` 常量解析项目名，改用服务端已经随组合一起下发的项目信息。做完后前端只剩测试与镜像守卫在读那份常量。

**Architecture:** 纯前端。`/api/applications` 的每一行已经带 `program`（`app/routers/applications.py`），而 `web/lib/programs-source.ts` 的适配器**故意声明了该字段却不读它**。本批就是把这个已经送到手边的数据用起来，并把常量的用途收敛到"镜像守卫的对照物 + 测试数据"。

**Tech Stack:** 无新依赖。前端测试用 node:test，先跑 `tsc --noEmit`。

**Spec:** `note/superpowers/specs/2026-10-06-stage-2-m2-design.md` §6、§8.6

## Global Constraints

- 源码注释、docstring、工程文档英文；`note/` 中文例外；UI 文案、运行时与测试字符串中文。
- Conventional Commits 1.0.0，**必须有 scope**，**必须有非空英文 body**，body 每条 `- ` 开头。
- 不改写已推送历史，不 force-push。提交前 `git diff --cached --check`。
- **不引入新依赖。后端文件不得改动。**
- 不提交 `api/.env`、`api/.venv`、`web/.next*`、`.runtime-tools/`、`__pycache__`。
- 分支：`codex/stage-2-m2d-view-catalogue`。
- **不得删除 `web/lib/programs.ts`。** 它仍是镜像守卫的对照物与测试数据，直到数据标注阶段。
- **`null` 不得被渲染成空字符串。** 未知保持未知；服务端对 5 个字段可能返回 `null`。
- 走查新增的断言必须**能失败**。

---

### Task 1: 两个视图改用服务端下发的项目信息

**Files:**
- Modify: `web/components/HomeView.tsx`、`web/components/FlowView.tsx`、`web/lib/programs-source.ts`
- Create: `web/lib/programs-source.test.ts`（若无则建；已有则扩展）
- Modify: `scripts/e2e-walkthrough.cjs`

**Interfaces:**
- Consumes: `/api/applications` 每行的 `program` 字段（已存在）；`app.schemas.application` 的 `ProgramRef`
- Produces: `web/lib/programs-source.ts` 导出 `toProgramLabel(served) -> string | null` 或等价函数

- [ ] **Step 1: 写失败测试** —— 纯函数层面覆盖：
  - 有服务端项目信息时，标签来自它而不是常量数组
  - 服务端项目为 `null` 时**不渲染空字符串**，而是显示一个明确的"未知"文案（断言不等于 `""`）
  - 名字的取法遵守 M2a 记录的映射（前端 `name` ← 接口 `nameEn`）
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** —— `HomeView`/`FlowView` 改为从组合行的 `program` 取展示所需的字段；`programs-source.ts` 里那个"声明了却不读"的字段注释要相应更新。
- [ ] **Step 4: 走查断言（能失败）** —— 加一条：组合卡片渲染的项目名与**服务端下发**的一致。用突变证明它能红（例如把标签改回常量数组取，观察它是否会在两边不一致时失败）。
- [ ] **Step 5: 跑全量** `make test && make build && make verify`
- [ ] **Step 6: 提交**

**注意事项**：`web/components/HomeView.tsx` 与 `FlowView.tsx` 目前通过 `PROGRAMS.find(...)` 解析；若某项目不在常量数组里就会渲染成裸 slug。改完后这种状态应当**不可能出现**——因为数据来自服务端。请在报告里说明：常量数组现在还有哪些读者（预期只剩镜像守卫与测试）。

---

## 自检

| spec 要求 | 任务 |
|---|---|
| §6 `FlowView` 改用接口数据 | Task 1 |
| §8.6 前端组件不改 | 本批**有意**改动这两个视图（§8.6 的"组件不改"指向的是 M1/M2a 的档案页）；这是对 §6 的执行，记录在报告里 |
| 常量仍是镜像守卫的对照物 | Task 1 Step 6 |

**风险**：`FlowView` 渲染的是路线图阶段，而组合行带的是项目——这两处数据结构不同。若某个阶段需要项目名而当前上下文拿不到，实现者应当报告并说明，而不是从常量里偷偷取。

## 执行方式

Subagent-Driven，1 个任务。
