# 第二阶段 M2 设计：选校组合与申请进度落库

日期：2026-10-06
状态：**待用户批准**（批准前不写代码）
前置：M1 已合并进 `main`（PR #2，merge commit `946b867`）
上位 spec：`note/superpowers/specs/2026-10-06-stage-2-database-design.md`

---

## 1. 目标

把仍然只存在浏览器里的两样东西搬到服务器：**选校组合**与**申请进度**。做完之后，用户的全部数据都在服务端。

同时补上 M1 留下的一个缝：`GET /api/programs` 已经能用，但前端还在读代码里那份硬编码的 `web/lib/programs.ts`。M2 接上它。

## 2. 本阶段范围

**做**：5 张表 + 迁移 + 种子；路线图定义入库；前端选校组合与进度脱离 localStorage；项目目录接口接上；`origin` 归属规则与重算逻辑。

**不做**：agent 本体、材料上传、审核依据、会话与消息（M3/M4）。**不做**手动的拖拽排序、"自定义任务"这类编辑器功能。

---

## 3. 关键设计决策

### 3.1 算法留在浏览器，算完存服务器（用户已确认）

前端 `web/lib/roadmap.ts` 的倒推算法**保持现状**，不在 Python 里重写一份。理由：算法只写一遍，不存在两边算得不一样的风险；迁移当天日期不会变。

**代价（已知并接受）**：服务器无法独立算出路线。半夜批处理重算、agent 无浏览器推算，这两件事现在做不到。等真需要时再把算法搬过去，届时前端那份就是标准答案。

### 3.2 每一行都要标来源（`origin`）—— 这是本阶段的核心规则

问题：用户改了档案 → 浏览器重算 → **整条路线被覆盖** → agent 之前帮他加的任务被冲掉。

所以 `roadmap_tasks` 与 `applications` 都带 `origin`：

| origin | 谁写的 | 浏览器重算时 |
|---|---|---|
| `system` | 前端倒推生成 | **只替换这一类** |
| `user` | 用户自己调整的 | 原样保留 |
| `agent` | agent 写的 | 原样保留 |

**这个规则与"谁算"无关** —— 就算改成服务器算，重算一样会冲掉 agent 的改动。所以这是"从档案重算"这件事本身的代价，不是选型的代价。

### 3.3 重算是 upsert，不是删光重建

系统行的身份是 `(client_id, material_key, program_id)`。重算时：

- 该存在但不存在 → 插入
- 已存在 → 只更新日期字段，**保留 `status` 与 `origin`**
- 不再适用（例如换了目标方向）→ 删除，但**只删 `origin = 'system'` 的**

这样用户勾过的完成状态不会因为一次重算而丢失。

这套删除规则有一个前提，**M2b 开工前必须先读 3.8**：重算必须由"确实从服务端读到的定义"驱动。

`program_id` 用**空字符串**而不是 NULL。Postgres 里 `UNIQUE` 不约束 NULL，用 NULL 会让"同一份材料对多个项目各一行"的唯一性失效。

### 3.4 路线图的定义入库，浏览器取

阶段与材料的定义（现在写死在 `web/lib/roadmap.ts`）搬进库里播种。理由：agent 需要知道有哪些材料才能引用它们；以后数据标注要修正清单时也不用改代码。

浏览器需要定义才能算，所以它和任务行**一起取**（一个请求）。定义是只读配置，前端不再有第二份。

### 3.5 新增第 7 个阶段：签证

现在 6 个阶段到「Offer 与入学」就结束了，签证和行前没有位置。GS 属于这一阶段，M3 的材料审核要用。

### 3.6 项目名中英文的归属（M1 遗留）

M1 的接口把中文放 `name`、英文放 `nameEn`，而前端 `Program.name` 存的是英文。**裁定：接口不改，前端适配器做映射** —— 前端的 `name` 取接口的 `nameEn`。

理由：数据库里 `name` 是中文、`name_en` 是英文，这对中文产品是自然形状；前端选择显示英文名是产品决策，不是接口决策。这个分歧 M1 已写进接口文档，M2 的适配器遵守它，并**加测试钉住**。

同时修正前端类型里与接口不符的可空性：接口对 5 个字段返回 `string | null`，前端类型声明为非空。前端改成 `string | null` 并显式渲染"未知"，**不把 null 转成空字符串**（那是把未知说成已知）。

### 3.7 `task_events` 从 M2 就开始写

不只 agent 写入，用户的勾选与调整也记一条。理由：3.2 的归属规则要有可追溯性 —— 出了分歧要能查出"这行是谁、什么时候、因为什么改的"。

### 3.8 重算与写必须由"服务端读到的定义"驱动（M2b 的硬约束）

M2a 已定型的降级路径里有一个隐患，M2b 写重算之前必须先处理，否则 3.2 的归属规则会被自己的降级路径打穿：

- `web/lib/roadmap.ts` 的 `DEFAULT_DEFINITION` **故意不含签证阶段**（签证在 `api/app/seed_roadmap.py` 里才有），它是"读不到服务器时的内置副本"，不是真相的第二份。
- `web/app/page.tsx` 把这份内置定义**喂给同一个 `buildRoadmap` 调用**，与"服务端读到的定义"只靠提示标志（`roadmapNotice`）区分 —— 也就是：**页面自己知道在用副本，但算出来的是同一形状的一份路线**。
- M2b 的重算按 3.3 是"不再适用的系统行删除"。用内置副本跑一次重算，算出的签证材料数是 **0**，于是签证的系统行被当作"不再适用"删掉；下一次用真定义跑，它们以 `pending` 重新插入，原来的 `status` 与 `completed_at` 就此丢失 —— 正是 3.2 的 `origin` 规则要防的那种丢失。

提示条只是**告诉人**，它**不拦写**。所以 M2b 必须同时满足两条：

1. **重算与它的写入以"定义确实来自服务端"为前提。** 读失败走内置副本时只渲染、不落库；没有服务端定义就不重算，也不 `PUT`。
2. **客户端显式提交"本次适用的材料键集合"**，服务端据此区分"不再适用（删除）"与"这次没带上（不动）"。只凭请求体里缺某个键就删除，等于把一次不完整的请求当成一次完整的重算。

M2a 本批**不实现**重算，只把这两条约束记在这里；验收标准见 8 的第 2、3 条。

---

## 4. 实体

### 4.1 新增

**`roadmap_phases`** — 阶段定义（配置）

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | TEXT PK | 如 `selection` |
| `title` / `subtitle` | TEXT | |
| `offset_days` | INT | 相对入学日倒推 |
| `sort_order` | INT | |

**`material_templates`** — 材料清单（配置）

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | TEXT PK | 如 `aca-transcript` |
| `phase` | TEXT FK roadmap_phases | |
| `title` / `detail` | TEXT | |
| `applies_to` | TEXT | all / research / portfolio |
| `sort_order` | INT | |
| `source_id` | TEXT FK sources NULL | 有官方依据的材料项可挂来源 |

**`roadmap_tasks`** — 每个用户的任务

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `client_id` | TEXT FK clients CASCADE | |
| `material_key` | TEXT FK material_templates | |
| `program_id` | TEXT NOT NULL DEFAULT '' | per-program 材料；空串表示与项目无关 |
| `phase` | TEXT | 冗余，便于查询 |
| `status` | TEXT | pending / in_progress / completed / skipped |
| `suggested_at` / `due_at` | DATE NULL | |
| `schedule_origin` | TEXT | suggested / official / user |
| `origin` | TEXT | **system / user / agent** |
| `document_id` | TEXT NULL | M3 用 |
| `completed_at` | TIMESTAMPTZ NULL | |

约束：`UNIQUE (client_id, material_key, program_id)`；索引 `(client_id, phase)`。

**`applications`** — 选校组合

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `client_id` | TEXT FK CASCADE | |
| `program_id` | TEXT FK programs | |
| `tier` | TEXT | 冲 / 稳 / 保 |
| `status` | TEXT | considering / applying / excluded |
| `is_primary` | BOOLEAN | |
| `official_deadline` | DATE NULL | |
| `deadline_source_url` | TEXT NULL | |
| `needs_review` | BOOLEAN | 系统判不出档位、用户自行加入 |
| `origin` | TEXT | **user / agent** |
| `created_at` / `updated_at` | | |

约束：`UNIQUE (client_id, program_id)`；**部分唯一索引保证每个用户至多一个 `is_primary = true`**。

**`task_events`** — 变更历史

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `client_id` | TEXT FK CASCADE | |
| `task_id` | TEXT NULL | 任务被删后仍保留事件 |
| `application_id` | TEXT NULL | |
| `actor` | TEXT | user / agent / system |
| `event` | TEXT | created / status_changed / rescheduled / reassigned / removed |
| `before` / `after` | JSONB NULL | |
| `message_id` | TEXT NULL | M4 关联对话 |
| `created_at` | | |

### 4.2 沿用 M1

`clients` `profiles` `sources` `programs` `universities` `program_prerequisites` 不动。

---

## 5. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/roadmap` | 返回 **定义 + 该用户的任务行**，一次拿全 |
| `PUT` | `/api/roadmap/tasks` | 重算后的系统行批量 upsert；服务端**只覆盖 `origin='system'` 的** |
| `PATCH` | `/api/roadmap/tasks/{id}` | 用户改单条：状态、日期。改完 `origin` 变 `user` 并写 `task_events` |
| `GET` | `/api/applications` | 选校组合，带项目信息 |
| `PUT` | `/api/applications` | 整体替换用户的组合（与现有确认流程一致），写 `task_events` |
| `GET` | `/api/programs` | M1 已有，M2 开始被前端使用 |

全部沿用 M1 的匿名 cookie 身份。**跨主体读写必须被拒绝，且要有测试**（M1 的隔离测试被终审指出"证明不了 cookie 被读过"，M2 的新接口要测到这一点）。

---

## 6. 前端改动

- `web/lib/api.ts` 增加路线图与组合的读写函数
- `web/lib/store.ts`：`portfolio` 与 `completedMaterials` 移出；localStorage 只剩 `stage`
- `web/lib/programs.ts`：前端不再作为数据源，改为从 `/api/programs` 取；**保留为测试夹具与镜像守卫的对照物**，直到数据标注阶段
- 新增适配层：接口 camelCase 与前端类型之间，含 `name ← nameEn` 映射、5 个字段的可空性修正
- `Onboarding` / `PortfolioPicker` / `FlowView` 改为读接口数据
- **重算时机**：打开时读服务器；若服务器无任务行，或档案的 `updated_at` 晚于最后一次系统重算时间，则重算并 `PUT`

---

## 7. 分批

| 批 | 内容 | 独立验收 |
|---|---|---|
| **M2a** | `roadmap_phases` + `material_templates` + 种子（含签证阶段） | 定义能在库中查到；接口返回定义 |
| **M2b** | `roadmap_tasks` + `task_events` + 重算 upsert 与 `origin` 规则 | 重算不冲掉 `user`/`agent` 行；完成状态不丢 |
| **M2c** | `applications` + 接口 + 前端组合脱离 localStorage | 换设备组合还在；至多一个首选 |
| **M2d** | 项目目录接口接上 + 适配层与可空性修正 | 前端不再读 `programs.ts` 作为数据源；走查通过 |

每批一个 PR，各自可独立验收。

---

## 8. 验收标准

1. 迁移从空库能一次建全；`downgrade base` 能干净回退
2. **重算只覆盖 `origin = 'system'` 的行**（要有测试：先造一条 `agent` 行，跑重算，证明它还在）
3. **重算不丢完成状态**（先勾选完成，跑重算，证明仍是 completed）
4. 每个用户至多一个 `is_primary = true`（数据库约束 + 测试）
5. 跨主体读写被拒绝，且测试**证明申请方的 cookie 真的被读过**（M1 的测试在这点上不够）
6. 前端组件不改（`ProfileView` 等），端到端走查仍通过
7. 路线图日期与 M1 的前端算法**逐项一致**（迁移前后同一份档案算出的日期不变）
8. `task_events` 在用户改动与重算两条路径上都留下记录

---

## 9. 风险与未决

| 项 | 说明 |
|---|---|
| 前端持有算法 | 服务器无法独立重算。已知并接受，代价记在 3.1 |
| 定义入库后的首屏 | 路线图页现在依赖一次接口调用。接口失败要有明确降级，不能白屏 |
| `program_id` 用空串 | 为了唯一约束。文档与测试里要点明这层含义，避免后人以为是脏数据 |
| 前端不再以 `programs.ts` 为数据源 | 但镜像守卫仍用它做对照。M3 数据标注完成后，两者一起退役 |
| 时区 | 日期倒推用设备本地时间。跨时区用户的 `suggested_at` 可能差一天。M2 不处理，记录下来 |
