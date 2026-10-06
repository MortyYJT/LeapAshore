# 第二阶段设计：数据库与服务端

日期：2026-10-06
状态：**待用户批准**（批准前不写任何代码）
前置：第一阶段（前端骨架）已合并进 `main`，线上站点为 https://web-gamma-sepia-86.vercel.app

---

## 1. 目标

把前端的 localStorage 状态搬到服务端，并把 agent 需要的数据结构一次性设计到位：

1. 用户档案、选校组合、申请进度、上传材料**落库**，换设备/清缓存数据仍在
2. 项目数据入库，为后续**数据标注**做准备
3. 支撑下一阶段 agent 的四类能力：
   - 对话改路线与材料准备
   - 上传材料后自动归档分类
   - 进度分析
   - 材料审核并给建议（含签证 GS）

## 2. 本阶段范围

**做**：表结构 + 迁移脚本 + 后端骨架（FastAPI）+ 读写接口 + 前端切换到接口。

**不做**：Agent 本体、模型调用、文件内容解析（OCR/PDF 抽取）、数据标注的实际录入、账号登录。

## 3. 关键设计决策

### 3.1 单一 PostgreSQL，文档型处用 JSONB，不引入第二个数据库

决策依据：

| 理由 | 说明 |
|---|---|
| 真正文档型的只有三处 | 档案整体读写、agent 每轮的工具调用与证据、材料审核的原始模型输出 |
| 其余都是关系型 | 项目、选校组合、进度、会话、消息、材料都要 join、唯一约束、外键 |
| 旧项目的前车之鉴 | 旧实现是 PostgreSQL + MySQL 双库，出现了「删号没有传播到第二个库」的缺陷 |

**什么时候才值得引入第二个库**：等要存整页官网快照、知识块、向量时（数据标注 / RAG 阶段），那时的选择是对象存储或 Milvus，不是通用文档库。

### 3.2 来源治理统一成两张表

`program_sources` 与 `review_criteria` 都依赖同一套东西：官方 URL、摘录、核验状态、核验时间、版本快照。因此抽成 `sources` + `source_versions` 两张通用表，项目与审核要点都指向 `sources`，**不重复实现两套来源版本机制**。

### 3.3 材料是有生命周期的实体，不是一行元数据

```
上传 → 归档分类 → 送审 → 有反馈 → 修改重传
```

因此拆成 `documents`（身份、状态、关联）+ `document_versions`（每次上传的文件）+ `document_reviews`（每次审核）+ `document_review_findings`（每条具体建议）。

**文件本体不进数据库**：存服务器本地目录，库里只存路径、大小、sha256。理由：数据库存二进制会让备份与迁移变重，而且现在没有对象存储的必要。

### 3.4 审核建议必须能回溯到官方来源

用户已确认选 A。因此 `document_review_findings` 通过 `criterion_id` 指向 `review_criteria`，而 `review_criteria` 必须带 `source_id`。**没有来源的审核要点不允许入库。**

### 3.5 agent 的写操作先落成待确认提案

沿用第一阶段的「写操作分级确认」：

| 风险 | 操作 | 行为 |
|---|---|---|
| 低 | 归档材料、标记任务完成、记录截止日期 | 直接执行 |
| 高 | 改路线、改申请组合、改档案关键字段 | 落成 `proposals` 行，等用户确认才生效 |

`proposals` 表让「agent 提了什么、用户确认了没有」可追溯。

### 3.6 身份模型：匿名设备 ID

前端目前没有登录。用 `clients` 表承载匿名主体（cookie 里一个 UUID）。不引入登录界面，但数据结构让以后加账号能平滑迁移。

### 3.7 技术选型

| 项 | 选择 | 理由 |
|---|---|---|
| 数据库 | PostgreSQL 16（Docker） | 本机 Docker daemon 已确认运行；简历写的也是 PostgreSQL |
| 迁移 | Alembic | 旧项目用过，能讲；支持版本化与回滚 |
| ORM | SQLAlchemy 2.0 | 事实标准；配合 Alembic 使用 |
| 后端 | FastAPI + Pydantic v2 | 与前端类型同形，能直接对照 `web/lib/types.ts` |
| Python | 项目本地 venv（3.12） | 系统默认 3.9 太旧；不污染全局环境 |
| 文件存储 | 项目本地目录（挂载卷） | 现在不需要对象存储 |

---

## 4. 实体清单

### 4.1 主体与档案

**`clients`** — 匿名主体

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | UUID，来自前端 cookie |
| `created_at` | TIMESTAMPTZ | |
| `last_seen_at` | TIMESTAMPTZ | |

**`profiles`** — 申请档案（一个 client 一行）

| 字段 | 类型 | 说明 |
|---|---|---|
| `client_id` | TEXT PK FK | |
| `current_education_level` | TEXT | 高中/本科/硕士/其他 |
| `school_origin` | TEXT | 国内/海外 |
| `school_name` | TEXT | |
| `domestic_tier` | TEXT | 985/211/双非/专科，可空 |
| `overseas_band` | TEXT | QS 区间，可空 |
| `major` | TEXT | |
| `gpa_score` / `gpa_scale` | NUMERIC | |
| `target_degree_level` | TEXT | |
| `target_field` | TEXT | |
| `intake` | TEXT | 如 2027 S1 |
| `english_score` | TEXT | 自由文本 |
| `annual_budget_cny` | NUMERIC | |
| `avatar_document_id` | TEXT FK documents | 可空 |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

**`profile_revisions`**（可选，审计 agent 改档案）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `client_id` | FK | |
| `changed_fields` | JSONB | `{字段: {before, after}}` |
| `actor` | TEXT | user / agent |
| `message_id` | FK messages | 可空，来自哪条对话 |
| `created_at` | TIMESTAMPTZ | |

### 4.2 项目与来源

**`sources`** — 官方来源（一个页面一条）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `url` | TEXT | 官方地址 |
| `title` | TEXT | |
| `publisher` | TEXT | 如 Department of Home Affairs |
| `domain` | TEXT | 用于白名单校验 |
| `status` | TEXT | 待核验 / 已核验 / 失效 |
| `verified_at` | TIMESTAMPTZ | **可空，不允许填假日期** |
| `created_at` / `updated_at` | | |

**`source_versions`** — 来源快照

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `source_id` | FK | |
| `requested_url` / `final_url` | TEXT | 重定向后地址 |
| `fetched_at` | TIMESTAMPTZ | |
| `content_type` / `content_bytes` | TEXT / INT | |
| `content_sha256` | TEXT | |
| `body_text` | TEXT | 截断到上限 |
| `status` | TEXT | pending_review / published / superseded / rejected |
| `reviewed_by` / `reviewed_at` / `review_note` | | 人工审核 |

**`universities`** — 学校

| 字段 | 类型 |
|---|---|
| `id` TEXT PK / `name` / `name_en` / `city` / `country` / `official_url` | |

**`programs`** — 项目

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | slug |
| `university_id` | FK | |
| `name` / `name_en` / `city` | TEXT | |
| `degree_level` / `field` / `duration` | TEXT | |
| `minimum_mark` | NUMERIC | 可空 |
| `non_211_minimum_mark` | NUMERIC | 可空 |
| `requires_cognate` / `requires_supervisor` / `research_proposal_required` | BOOLEAN | |
| `english_requirement` | TEXT | |
| `source_id` | FK sources | |
| `data_status` | TEXT | 待核验 / 已核验 |

**`program_prerequisites`** — 先修课明细

| 字段 | 类型 |
|---|---|
| `id` PK / `program_id` FK / `label` / `category` / `sort_order` | |

### 4.3 申请与进度

**`applications`** — 选校组合

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `client_id` / `program_id` | FK | |
| `tier` | TEXT | 冲 / 稳 / 保 |
| `status` | TEXT | considering / applying / excluded |
| `is_primary` | BOOLEAN | |
| `official_deadline` | DATE | 可空 |
| `deadline_source_url` | TEXT | 可空 |
| `needs_review` | BOOLEAN | 系统判不出档位、用户自行加入 |
| `created_at` / `updated_at` | | |

约束：`UNIQUE (client_id, program_id)`；**部分唯一索引保证每个 client 至多一个首选**。

**`material_templates`** — 材料模板（配置，非用户数据）

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | TEXT PK | 如 `aca-transcript` |
| `phase` | TEXT | 见下方阶段枚举 |
| `title` / `detail` | TEXT | |
| `applies_to` | TEXT | all / research / portfolio |
| `sort_order` | INT | |
| `default_offset_days` | INT | 相对入学日倒推 |

**`roadmap_tasks`** — 每个用户的进度

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `client_id` | FK | |
| `material_key` | FK material_templates | |
| `phase` | TEXT | 冗余存储，便于查询 |
| `status` | TEXT | pending / in_progress / completed / skipped |
| `suggested_at` / `due_at` | DATE | |
| `schedule_origin` | TEXT | suggested / official / user |
| `program_id` | FK programs | 可空，针对某项目的材料 |
| `document_id` | FK documents | 可空，已归档的材料 |
| `completed_at` | TIMESTAMPTZ | |

**`task_events`** — 任务变更历史（agent 改动的可追溯性）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `task_id` FK | | |
| `actor` | TEXT | user / agent |
| `event` | TEXT | created / status_changed / rescheduled / document_linked |
| `before` / `after` | JSONB | |
| `message_id` | FK messages | 可空 |
| `created_at` | | |

### 4.4 材料库

**`documents`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `client_id` | FK | |
| `title` | TEXT | 用户给的名字 |
| `kind` | TEXT | 空到归档为止：transcript / cv / ps / recommendation / language / passport / gs / other |
| `status` | TEXT | uploaded / archived / under_review / needs_revision / accepted |
| `task_id` | FK roadmap_tasks | 可空，满足哪个材料要求 |
| `program_id` | FK programs | 可空，PS 这类是按项目分的 |
| `current_version_id` | FK document_versions | 可空 |
| `archived_by` / `archived_at` | TEXT / TIMESTAMPTZ | 谁归档的：user 或 agent |

**`document_versions`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `document_id` FK / `version_no` INT | | `UNIQUE (document_id, version_no)` |
| `filename` / `mime_type` / `byte_size` / `sha256` | | |
| `storage_path` | TEXT | 服务器本地路径，**不进库的文件本体** |
| `uploaded_by` / `created_at` | | |

**`document_reviews`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `document_id` FK / `version_id` FK | | |
| `overall` | TEXT | pass / needs_revision / insufficient_evidence |
| `summary` | TEXT | |
| `run_id` | FK agent_runs | 可空，哪次 agent 执行产生的 |
| `created_at` | | |

**`document_review_findings`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `review_id` FK | | |
| `criterion_id` | FK review_criteria | **可空？不 —— 见验收标准** |
| `severity` | TEXT | info / warning / blocker |
| `finding` | TEXT | 具体建议 |
| `evidence_quote` | TEXT | 从材料里引用的原文 |

### 4.5 审核依据

**`review_criteria`** — 审核要点

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | |
| `code` | TEXT UNIQUE | 如 `gs-current-circumstances` |
| `scope` | TEXT | gs / transcript / cv / ps / recommendation / language / general |
| `title` / `description` | TEXT | |
| `check_type` | TEXT | presence / length / language / evidence / consistency |
| `rule` | JSONB | 可机检的规则，如 `{"maxWords": 150}` |
| `source_id` | FK sources | **必填** |
| `status` / `verified_at` | | 待核验 / 已核验 |

### 4.6 Agent

**`conversations`** → **`messages`**（一条会话挂多条消息）

| `conversations` | | `messages` | |
|---|---|---|---|
| `id` TEXT PK | | `id` TEXT PK | |
| `client_id` FK | | `conversation_id` FK | |
| `title` TEXT | | `seq` INT | `UNIQUE (conversation_id, seq)` |
| `created_at` / `updated_at` | | `role` TEXT | user / assistant / system |
| | | `content` TEXT | |
| | | `metadata` JSONB | 工具调用、证据、置信度、提案引用 |
| | | `created_at` | |

**`agent_runs`** — 一次 agent 执行

`id` / `message_id` FK / `workflow_version` / `prompt_version` / `provider` / `model` / `latency_ms` / `input_tokens` / `output_tokens` / `tool_calls` JSONB / `confidence` JSONB / `created_at`

**`proposals`** — 待确认的改动

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `client_id` FK / `conversation_id` FK / `message_id` FK | | |
| `kind` | TEXT | update_profile / update_roadmap / update_application / create_task / archive_document |
| `payload` | JSONB | 具体改动 |
| `risk` | TEXT | low / high |
| `status` | TEXT | pending / confirmed / rejected / expired |
| `resolved_at` / `created_at` | | |

---

## 5. 阶段枚举（`phase`）

第一阶段是 6 个阶段，需要**新增第 7 个签证阶段**（GS 属于这里）：

```
selection 锁定申请组合
academic  学术与身份材料
language  语言准备
specialized 专项申请材料
submission 提交申请
decision  Offer 与入学
visa      签证与行前   ← 新增
```

## 6. GS 审核要点的来源（已核验）

来源：[Genuine Student requirement — Department of Home Affairs](https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/genuine-student-requirement)
页面自述最后更新：2026-09-24；本仓库抓取核验日期：2026-10-06

从官网原文可以直接提炼出**可机检**的要点（括号内为 `check_type`）：

1. 每题回答**不超过 150 词**（length，`rule: {"maxWords": 150}`）
2. 回答**必须用英文**（language）
3. 需说明**当前情况**：家庭、社区、就业、经济联系（presence）
4. 需说明**为什么选这个课程与这个学校**，并对课程要求与在澳生活有理解（presence）
5. 需说明**课程如何有利于本人**（presence）
6. 陈述**需有证据支持**：成绩单、雇主信息、税单或银行流水等（evidence）
7. 若本国存在同类课程，需说明**为何不在本国就读**（presence）
8. **移民历史**：签证与旅行记录、以往的申请、拒签或取消记录（presence）
9. 未成年人另需考虑父母/法定监护人/配偶的意图（presence）
10. GS 适用于 **2024-03-23（含）之后**递交的申请；该日期之前适用 GTE（consistency）

评估维度共 5 项：本国情况 / 在澳情况 / 课程对未来的价值 / 移民历史 / 其他事项。官方另引用 Ministerial Direction No. 106。

**注意**：以上是"审核要点的骨架"。每一条在正式录入时都必须带官网 URL 与核验时间，且 `status` 初始为 `待核验`，不允许直接标成已核验。

---

## 7. 迁移分批

不一次性建 21 张表，按可独立验收的批次来：

| 批次 | 内容 | 验收 |
|---|---|---|
| M1 | `clients` `profiles` `universities` `programs` `program_prerequisites` `sources` `source_versions` | 项目数据从种子导入；档案可读写；换设备数据还在 |
| M2 | `material_templates` `roadmap_tasks` `applications` `task_events` | 前端选校组合与进度脱离 localStorage |
| M3 | `documents` `document_versions` `document_reviews` `document_review_findings` `review_criteria` | 能上传文件、能归档、能写入一条带来源的审核结论 |
| M4 | `conversations` `messages` `agent_runs` `proposals` | 会话与消息可读写；提案可确认/拒绝 |

**每一批单独一个 PR。**

---

## 8. 验收标准

1. `alembic upgrade head` 从空库能一次建全；`alembic downgrade base` 能干净回退
2. 每一张用户数据表都有 `client_id` 或其外键链路，**跨主体读取会被拒绝**（要有测试）
3. **`document_review_findings.criterion_id` 不可为空**：没有来源的建议不允许入库（要有测试）
4. `sources.verified_at` 允许为空，**不允许出现硬编码的假日期**（要有测试）
5. 每个 client 至多一个 `is_primary`（要有测试）
6. 前端 `lib/store.ts` 换成接口调用后，**组件不改**，端到端走查仍通过
7. 文件上传：能上传、能按 sha256 去重、大小与类型有上限

## 9. 风险与未决

| 项 | 说明 |
|---|---|
| Python 环境 | 系统 3.9 太旧；需先建项目本地 3.12 venv（或装 uv）。**这是第一个要动手解决的前置条件** |
| 前端类型同形 | `web/lib/types.ts` 用的是 camelCase，数据库是 snake_case，需要在 API 层做映射；不要两边各写一套 |
| GS 要点数量 | 本 spec 只提炼了骨架；正式录入时的完整清单需要一次专门的标注工作 |
| 文件存储位置 | 现在存本地目录，部署到 Vercel 时**不可用**（无持久磁盘）。届时需要对象存储，或后端不走 Vercel |
| 本阶段不做登录 | 匿名设备 ID；清 cookie 会丢数据，界面上要说明 |
