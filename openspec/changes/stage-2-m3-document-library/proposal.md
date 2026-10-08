# stage-2-m3-document-library

## Why

阶段二 M1–M2 把档案、选校组合、申请进度都搬到了服务端，但"要准备的材料"目前只剩一个勾选框：申请人手里的成绩单、简历、PS 没有地方放，系统既不知道他到底交了什么文件，也无从判断够不够。

同时，产品最核心的那条承诺——每个事实都能回溯到官方页面——还差最后一段：`sources` 表在 M1 就建好了，M2a 把签证材料挂到了 Genuine Student 官网页面上，但**审核依据本身**（`review_criteria`）一行都不存在。没有它，M4 的 Genuine Student 审核没有落点。

M3 把这两段接起来：材料有地方存（上传 / 版本 / 归档），审核有依据可查（带官方来源的 `review_criteria`），人工审核结论可以写进来并指回它引用的那一条依据。

## What Changes

- 新增 `documents` 与 `document_versions` 两张表：材料是有生命周期的实体（上传 → 归档分类 → 送审 → 有反馈 → 修改重传），不是一行元数据。
- 文件本体不进数据库：内容寻址（content-addressed）存在一个受配置控制的目录下，库里只存 sha256、字节数、MIME 与**相对**路径。
- 上传限额与类型白名单：单文件 20 MiB，只接受 PDF / PNG / JPEG / DOCX，按魔数校验而不是只信客户端声明的 Content-Type。
- 归档（分类）与审核状态流转：`uploaded → archived → under_review → needs_revision / accepted`，非法流转返回映射过的错误码而不是静默接受。
- 新增 `review_criteria`：审核要点必须有 `source_id`（NOT NULL），没有官方来源的要点不允许入库。
- 种子录入 10 条 Genuine Student 审核要点骨架，`status` 全部为 `待核验`，`verified_at` 留空——核验状态只能由人设置。
- 新增 `document_reviews` 与 `document_review_findings`：`criterion_id` NOT NULL，每条建议必须指向一条带来源的要点；`overall = pass` 与存在 `blocker` 的建议互相矛盾，会被拒绝。
- 维护者 CLI（`api/review_cli.py`）：核验审核要点、写入一条带 `criterion_id` 的审核结论。**HTTP 接口只读**——仓库没有登录与管理员角色，开放写接口等于任何访问者都能把要点标成"已核验"。
- 前端材料库：在路线图的任务行上传材料，材料库视图列出材料、版本、状态与分类，可下载、可归档、可送审，并能看到审核结论引用的是哪一条要点、出自哪个官方页面。
- 新增依赖 `python-multipart`（FastAPI 解析 multipart 上传所需）。

**不做**：文件内容解析（OCR / PDF 抽取）、agent 写入审核结论与会话（M4）、对象存储、账号登录、材料删除、按项目索引材料（`documents.program_id` 在 M3 恒为 NULL）、Genuine Student 之外的审核要点录入。

## Capabilities

### New Capabilities

- `document-library`：材料的身份、上传、版本、归档分类、审核状态流转、下载与跨主体隔离；以及申请人在界面上使用它的方式。
- `review-criteria`：审核要点的定义与其官方来源绑定，"待核验 / 已核验"状态只能由人推进。
- `document-review`：一次人工审核的结论与逐条建议，每条建议必须引用一条带来源的要点。

### Modified Capabilities

无。`openspec/specs/` 目前是空的（OpenSpec 在上一次会话才初始化），M3 是第一个 change；阶段一与 M2a–M2d 的实现早于 OpenSpec，没有已归档的 current-truth spec 需要修改。

## Impact

- **数据库**：一次新的 Alembic 迁移，新建 5 张表（`documents`、`document_versions`、`document_reviews`、`document_review_findings`、`review_criteria`）。不改动任何既有表的结构，不删除任何列。
- **后端**：`api/app/models`、`api/app/schemas`、`api/app/routers`、`api/app/services` 各新增文件；新增 `api/app/seed_review_criteria.py` 与 `api/app/review_cli.py`；`seed_cli.py` 与 `main.py` 各接一行。
- **前端**：`web/lib/types.ts`、`web/lib/api.ts`、`web/app/page.tsx`（把已有的服务端任务行映射成"材料 → 任务 id"，供上传时挂靠）、新增材料库组件与导航入口。
- **依赖**：`api/pyproject.toml` 新增 `python-multipart`；`make api-install` 与 CI 的既有安装命令不变。
- **存储**：新增一个被 git 忽略的文件目录，路径由 `Settings` 给出，默认由 `app/` 的位置推出（`api/var/documents`）。
- **线上可用性**：材料上传只在本地可用。线上既有"没有持久磁盘"的限制，又有 Vercel 函数约 4.5 MB 的请求体上限，20 MiB 的上传在那里到不了后端；M3 不声称线上可用，把它记进 design 的 Open Questions。
- **检查**：`scripts/check-no-fake-dates.cjs` 会扫描新代码；审核要点的种子数据不得出现硬编码的 `verified_at` 日期。
- **测试清理**：`api/tests/conftest.py` 的路线图定义清扫必须带上 `review_criteria`（以及指向它的 findings），否则 `sources` 的外键会让整个测试运行变红。
