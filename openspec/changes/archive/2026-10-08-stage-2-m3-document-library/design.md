# 设计：材料库与审核依据（阶段二 M3）

上位设计：`note/superpowers/specs/2026-10-06-stage-2-database-design.md`（§3.3、§3.4、§4.4、§4.5、§6、§7、§8）
本 change 的 proposal：`proposal.md`

---

## Context

M1 建好了 `sources` / `source_versions` 与两条已经落地的规则：`verified_at` 允许为空、没有 server default；`programs.source_id` 是 NOT NULL。M2a 把签证阶段的材料挂到了 Genuine Student 官网页面上，M2b 建了 `roadmap_tasks`，其中 `document_id` 是一列**故意没有外键**的裸列，就是给 M3 留的位置（`api/app/models/task.py:68`）。

现在缺的是三块：

1. 材料本身没有表。申请人勾了"成绩单"这个勾，但成绩单文件无处可放，`roadmap_tasks.document_id` 永远为 NULL。
2. `review_criteria` 不存在。`api/tests/test_programs_api.py:117` 的注释已经写下"`review_criteria.source_id` 与 `document_review_findings.criterion_id` 一直是 NOT NULL"——这句话目前还不是事实，M3 要让它成为事实。
3. 审核结论无处可写，因此 M4 的 Genuine Student 审核没有落点。

约束（来自仓库，不是设计选择）：

- 身份是匿名 cookie（`clients`），**没有登录、没有角色**，因此没有"管理员"这个概念可以挂在 HTTP 接口上。
- `scripts/check-no-fake-dates.cjs` 扫描 `api/` 与 `scripts/` 下的 `.py/.json/.cjs`，任何硬编码的 `verified_at` 日期直接让 `make verify` 失败。
- `api/tests/conftest.py` 在 session 级清扫路线图定义，并删除它创建过的 `clients`（依赖数据库级联）。
- `make verify` 包含真实浏览器走查（`scripts/e2e-walkthrough.cjs`），前端改动必须有截图证据。

## Goals / Non-Goals

**Goals:**

- 申请人能上传材料、看到版本、给材料分类归档、送审，并且换设备后这些数据仍在。
- 审核要点必须带官方来源才能入库；"已核验"只能由人推进。
- 一条审核结论必须能回溯到它引用的要点，以及该要点引用的官方页面。
- 材料、版本、建议的每一次写入都受主体隔离，跨主体读写被拒绝。

**Non-Goals:**

- 文件内容解析（OCR / PDF 抽取）、自动分类、自动审核——M4 的 agent 才做，M3 只保证"人写进来能被正确存下与读回"。
- 对象存储。文件仍在本地目录；父设计 §9 已记下 Vercel 无持久磁盘这个限制。
- 账号与管理员界面。因此核验与审核结论走 CLI（见 D8）。
- 材料的删除。M3 不提供任何删除接口，也不删磁盘上的文件（见 D11）。
- 除 Genuine Student 之外的审核要点录入。其余科目的要点属"数据标注"里程碑（路线图第 3 项）。
- `documents` 之外的新表：`conversations` / `messages` / `agent_runs` / `proposals` 属 M4。

## Decisions

### D1 文件本体内容寻址存储，版本行只存相对路径

布局：`<document_storage_root>/blobs/<sha256 前两位>/<sha256>`。`document_versions.storage_path` 存 `blobs/ab/abcd…` 这样的**相对**路径。

存储根本身默认由 `app/` 包的位置推出（`<repo>/api/var/documents`），不依赖进程 cwd：`make api-test`、`make api-dev` 与从仓库根直接跑脚本的 cwd 各不相同，用相对 cwd 的默认值会让文件散落在不同目录。

- 相对路径是硬要求：`.gitignore` 与隐私规则都不允许把本机绝对路径写进库或响应。
- 内容寻址让"按 sha256 去重"（父设计 §8.7）自然成立：同样的字节只落一次盘。
- 备选一：每个材料一个目录 `<client>/<document>/<version>-<原文件名>`。去重要另建索引，且原文件名会带来路径穿越与重名问题。
- 备选二：二进制进库（`bytea`）。备份与迁移变重，且父设计 §3.3 已明确否决。

`storage_path` 在内容寻址下其实可以由 `sha256` 推出来，仍然保留这一列：将来换成对象存储时，改变的是这一列的取值，而不是每一处拼路径的代码。

### D2 跨主体共享 blob 是安全的，但下载必须过版本行

两个不同主体上传同样的字节时，磁盘上是同一个文件。这不构成泄露：blob 路径不出现在任何响应里，下载走 `GET /api/documents/{id}/versions/{n}/file`，先校验该 document 属于调用者。知道一个 sha256 并不能读到别人的文件。

### D3 上传限额：单文件 20 MiB，四种类型，按魔数校验

- 大小：`20 * 1024 * 1024` 字节。**两处设限**，见 D4：先按声明的 `Content-Length` 直接拒绝超限请求，再在写入存储根时按实际字节数中止。不把整个文件读进内存判断。
- 类型：`application/pdf`、`image/png`、`image/jpeg`、`application/vnd.openxmlformats-officedocument.wordprocessingml.document`，其余 415。
- **入库的 `mime_type` 是魔数判定的结果，不是客户端声明的 Content-Type。** 只信声明的话，把 HTML 改名成 `.pdf` 就能存进"已归档材料"，再被浏览器以 `text/html` 取回——存储型 XSS。
- DOCX 除了 `PK\x03\x04` 之外，还要用标准库 `zipfile` 确认存在 `word/document.xml`：ZIP 头只能说明"这是个 zip"。
- 下载响应带 `Content-Disposition: attachment` 与 `X-Content-Type-Options: nosniff`，文件名用 RFC 5987 的 `filename*=UTF-8''…`（材料名是中文）。

### D4 上传的写入顺序：先落盘，再写库

一个必须先说清楚的机制：FastAPI 的 `UploadFile` 背后是 Starlette 的 multipart 解析器，它在**端点函数运行之前**就把每个文件分片 spool 成临时文件（`SpooledTemporaryFile`，超过 `max_size` 后落到系统临时目录）。所以"在 handler 里边读边限"并不能阻止一个超大请求体先被收下来。因此限额设在两处：

1. 请求带的 `Content-Length` 超过上限（或分片自身声明超限）时，在读 body 之前就返回 413。
2. 从 spool 文件往存储根搬运时按 64 KiB 分块、同时算 sha256 与字节数，超过上限立即中止并删除已写入的部分——**存储根下永远不会留下超限文件**。伪造长度、边传边涨的恶意客户端受限于第 2 条：它最多让系统临时目录承受一次请求体，且请求结束即清理。

其余步骤：

3. 校验魔数（D3），空文件 422。
4. 落盘：`sha256` 对应的 blob 已存在则复用；否则在同一目录写临时文件后 `os.replace` 就位（同分区内原子）。
5. 写 `document_versions`（首次上传还要写 `documents`），一个事务。

这个顺序的失败模式是**孤儿 blob**（盘上有、库里没有），永远不会是"库里的行指向不存在的字节"。M3 不删 blob（D11），所以孤儿只是浪费一点磁盘，不产生错误。

### D5 版本不可变，`version_no` 从 1 递增

`UNIQUE (document_id, version_no)`。新版本把 `status` 置回 `uploaded`，但**保留 `kind` 与 `archived_at`**：分类是"这份材料是什么"，不因为换了文件而改变。

并发上传同一材料时 `max+1` 可能撞唯一约束：服务内重试一次，仍然失败返回 409，而不是 500。

每个版本写 `uploaded_by`。M3 里没有 agent，因此这个值目前恒为 `user`；留着这一列是因为它记录的是"谁交的"，与 agent 到来后必须区分的那件事是同一件（父设计 §3.5 的写操作分级）。

### D6 审核状态是一组明确允许的流转

| 起点 | 动作 | 终点 | 谁能做 |
|---|---|---|---|
| — | 上传 | `uploaded` | 申请人 |
| 除 `under_review` 外任意 | 归档（必须给 `kind`） | `archived` | 申请人 |
| `archived`、`needs_revision` | 送审 | `under_review` | 申请人 |
| `under_review` | 审核 `pass` | `accepted` | 维护者 CLI |
| `under_review` | 审核 `needs_revision` | `needs_revision` | 维护者 CLI |
| `under_review` | 审核 `insufficient_evidence` | 不变（仍 `under_review`） | 维护者 CLI |
| 任意 | 上传新版本 | `uploaded` | 申请人 |

三条不显然但重要的规则：

- **送审前必须先归档。** 审核要点是按材料类型分的（`review_criteria.scope`），一份没分类的材料无法确定该用哪些要点去审，系统也不该猜。
- **`under_review` 期间不允许重新归档。** 审核正引用着该材料类型的要点，中途换分类会让这次审核的判据在它脚下被换掉。
- `insufficient_evidence` 不改状态：这次审核没能得出结论，材料仍在审核中，这也是"系统判不出来时说自己判不出来"在状态机上的体现。

### D7 `documents.current_version_id` 是循环外键，迁移里显式处理

`documents.current_version_id → document_versions.id` 与 `document_versions.document_id → documents.id` 互相引用。用 SQLAlchemy 的 `use_alter=True` 加显式约束名，让 alembic 在两个表都建好之后再 `ALTER TABLE` 补上这一条。手写迁移，不用 autogenerate 的裸输出。

### D8 人工写入走 CLI，HTTP 对审核依据只读

`api/review_cli.py`，风格对齐既有 `api/seed_cli.py`：

- `verify-criterion <code>` / `unverify-criterion <code>`：**全仓库唯一写 `verified_at` 的地方**，写入 `now()`，不写任何字面日期（`check-no-fake-dates` 会抓）。
- `review <document_id> --overall <…> --reviewed-by <name> --summary <…> --finding "<code>:<severity>:<text>"（可重复）`：一个事务内写 `document_reviews` + `document_review_findings`，并按 D6 推进材料状态。
- `--finding` 的解析固定为**按冒号切两刀**（`partition` 两次，等价于 `split(":", 2)`）：`code` 与 `severity` 里不可能有冒号，`text` 里几乎一定有（中文结论常带冒号）。少于两个冒号即参数错误，而不是把剩下的都当成 severity。

**为什么不开放 HTTP 写接口**：仓库没有登录与角色，任何 HTTP 写入口都等于"任何访问者都能把一条要点标成已核验、写一条假审核结论"。这与"`verified_at` 是人工设置、绝不默认"这条红线直接冲突。CLI 是本机操作，是当前身份模型下唯一诚实的入口。

备选：加一个共享 token 保护写接口。否决——那是给 M3 引入一套没有用户的鉴权，且 token 会进 `.env`，而仓库规则是不提交密钥、当前也没有任何密钥基础设施。

### D9 每条建议必须引用一条要点；结论与建议不得自相矛盾

- `document_review_findings.criterion_id` NOT NULL，外键 RESTRICT。
- `overall = pass` 时不允许存在 `severity = blocker` 的建议（422）。
- `overall != pass` 时至少要有一条建议：一句"需要修改"而不说改什么，对申请人没有用处。
- `general` 范围的要点可用于任何材料；其余要点只能用于 `kind` 与其 `scope` 相同的材料。`scope` 的取值与 `kind` 的取值刻意对齐（transcript / cv / ps / recommendation / language / gs），这不是巧合，而是让"这份 PS 缺少 150 词以内的 GS 回答"这类无意义结论在写入时就被拒掉。

两个取值的个数不同，这是有意的：`kind` 有八个（多出 `passport` 与 `other`），`scope` 有七个（多出 `general`，没有 `passport`）。后果要说清楚：**M3 里一份 `passport` 材料只能引用 `general` 要点，而 M3 的种子只写 `gs` 要点，所以护照材料在 M3 里审不了**。这是"只有 GS 要点有核验过的官方来源"的直接结果，不是遗漏；`general` 与护照类要点归"数据标注"里程碑。

### D10 审核绑定到具体版本

`document_reviews.version_id` NOT NULL。CLI 审核的必须是**当前版本**（`version_id == documents.current_version_id`），否则 409：审核进行中来了新版本，这次审核描述的是旧字节，应当重新审而不是照写。

`run_id`（父设计 §4.4 里指向 `agent_runs` 的列）**推迟到 M4**：`agent_runs` 表还不存在，为一张不存在的表建外键没有意义，先加一列裸列则要在 M4 再补一次迁移。M4 建 `agent_runs` 时一起加。

`reviewed_by` 是 M3 新增的一列（父设计没有），NOT NULL，由 CLI 的 `--reviewed-by` 传入：一条"谁说的"都无法回答的审核结论，不该入库。测试与文档里只用占位名，不写 owner 的真实姓名。

### D11 M3 不删除任何东西

没有 `DELETE /api/documents/...` 路由，也不做 blob 的引用计数与回收。理由：

- 材料的删除是一个需要用户确认的破坏性动作（"删掉我上传的成绩单"），属于 M4 的提案机制。
- 没有删除就不需要引用计数；跨主体共享 blob（D2）在删除面前才需要它。

对应的守卫写进 spec，并且把"没有这条路由"具体到路径，否则 405 测试写不出来：

| 路径 | 允许 | 其余方法 |
|---|---|---|
| `/api/documents` | `GET`、`POST` | 405 |
| `/api/documents/{id}` | `GET` | 405（含 `DELETE`） |
| `/api/documents/{id}/versions` | `POST` | 405 |
| `/api/documents/{id}/versions/{n}/file` | `GET` | 405 |
| `/api/documents/{id}/archive`、`/submit` | `POST` | 405 |
| `/api/documents/{id}/reviews` | `GET` | 405（含 `POST`） |
| `/api/review-criteria` | `GET` | 405 |

### D12 `documents.task_id` / `program_id` 用 ON DELETE SET NULL

`roadmap_tasks` 的行会被**重算删除**（M2b 的规则：只删 `origin='system'` 的行）。如果 `documents.task_id` 是默认的 RESTRICT，申请人一旦把材料挂到某个任务上，之后换目标就会让重算在删任务时撞外键、整次重算失败。`program_id` 同理，`api/tests/test_seed.py` 会删光所有项目。

`client_id` 则必须是 CASCADE：`api/tests/conftest.py` 的清扫依赖删 `clients` 时数据库级联带走从表。

### D13 材料与任务的关联只有一个方向

`documents.task_id` 是唯一权威的关联（"这份材料是在满足哪一条要求"）。`roadmap_tasks.document_id` 在 M3 **不写**：它是 M2b 留下的**反指针**，两列同时维护就有互相不一致的可能，而读的时候从 `documents` 反查是确定性的。

它已经在 `GET /api/roadmap` 的响应里（`api/app/schemas/task.py:158` 的 `documentId`），M3 不动它的形状，只是继续为 `null`。是否删掉这一列，留给下一个真正需要反查性能的批次决定，记在 Open Questions。

`documents.program_id` 同理，M3 **接受但不写**：父设计里它的用途是"PS 这类材料按项目分"，而 M3 的材料已经通过 `task_id` 挂到了具体任务上，而任务行自己就带 `program_id`（`api/tests/test_seed.py` 会删光项目，两列都是 SET NULL）。同一件事有两个来源就会有不一致，所以 M3 只保留任务那一条链路，`program_id` 恒为 NULL；真要按项目索引材料时再启用它。

### D14 前端：任务行上传 + 材料库视图

- `AppShell` 的 tab 增加"材料库"，渲染新的 `MaterialsView`。
- `FlowView` 的每条任务行增加上传入口：上传时带上该任务的 id，材料即挂在这条要求上。
- 任务 id 不由 `buildRoadmap` 提供：它只吃定义与 `completedMaterialIds`，从不接触服务端的 task 行（`web/lib/roadmap.ts:132`），因此 `PhaseTask` 的形状不必改。服务端的行本来就在 `page.tsx` 手里（`taskRows`，含 `id` 与 `material_key`），勾选状态就是这么算出来的（`web/app/page.tsx:423`）。上传入口走同一条路径：由 `page.tsx` 建 `material_key → task id` 的映射，`FlowView` 只回调一个 `materialId`。
- 映射不到任务时（该材料还没有服务端任务行——第一次写入失败、或路线图重算还没跑）**不拦上传**：材料照存，`task_id` 为 NULL。勾选状态在这个情况下本来就会提示"还没同步到服务器"，上传没有理由比它更严。
- 两个读取接口的分工要固定，否则载荷会失控：`GET /api/documents` 每个材料只带**当前版本**的摘要；`GET /api/documents/{id}` 才带完整版本列表（**最新在前**）与结论、逐条建议，以及每条建议引用的要点与官方页面。
- 下载走浏览器直接导航到 `/api/documents/{id}/versions/{n}/file`，不经过 fetch。
- 建议引用的要点会带出它来源的核验状态，因此界面必须复用既有的归一化方向（`programs-source.ts` 的 `toSourceStatus`：未知状态读成 `待核验`，绝不读成 `已核验`）。这条规则不能在新组件里重写一遍，否则 `失效` 的来源可能显示成已核验。

### D15 交付拆两个 PR，同一个 change

- **PR 1（后端）**：迁移、模型、服务、路由、种子、CLI、后端测试。完成后 `GET /api/documents` 等接口可用，前端尚未接线。
- **PR 2（前端）**：材料库视图、任务行上传、走查脚本新增步骤与截图。

两个 PR 都进 `main`（分支 `dsh/stage-2-m3-*`），用户合并。选这个拆法的理由：M2a–M2d 就是这么交付的，两个 PR 各自可独立验证，回滚粒度也更细。

### D16 上传接口的请求形状定死

上传是两个路由，都是 `multipart/form-data`，字段名固定如下（不额外挂 JSON body：同一个路由上 FastAPI 不能同时收 JSON 与表单，这正是要提前说清的原因）：

| 路由 | 字段 | 必填 | 说明 |
|---|---|---|---|
| `POST /api/documents` | `file` | 是 | 文件本体 |
| | `title` | 否 | 不给则用 `file` 的文件名 |
| | `task_id` | 否 | 要挂靠的任务；不给则是 NULL |
| `POST /api/documents/{id}/versions` | `file` | 是 | 新版本 |

`task_id` 的三种结局必须互不相同：

1. 是调用者自己的任务 → 挂上，`documents.task_id` 为该值。
2. 是别人的任务 → 422，不创建任何材料（与 `applications` 里"program id 指不到东西"的处理一致）。
3. 任务后来被重算删掉 → `task_id` 变 NULL，材料本身与文件都还在（D12）。

"别人的任务"与"已被删除的任务"因此必须分开判断：前者是拒绝，后者是接受。

## Risks / Trade-offs

| 风险 | 处理 |
|---|---|
| 测试会真的往开发库与磁盘写文件，且 `conftest.py` 的清扫顺序会撞外键 | 见下面单独一段：要改的不只是 fixture 的顺序，而是清扫函数本身 |
| `check-no-fake-dates.cjs` 会扫到种子里的要点数据 | 种子只写 `status="待核验"`，`verified_at` 一律不设；CLI 用 `now()` 生成时间 |
| `PUT /api/roadmap/tasks` 的重算会删任务行 | D12 的 SET NULL；并补一个测试：任务被删后材料仍在，`task_id` 变 NULL |
| 线上既没有持久磁盘，又有 Vercel 函数约 4.5 MB 的请求体上限，20 MiB 的上传在那里根本到不了后端（[Vercel KB](https://vercel.com/kb/guide/how-to-bypass-vercel-body-size-limit-serverless-functions)） | 父设计 §9 只记了磁盘那一半；两半都写进 Open Questions。M3 的验收只在本地进行，不声称线上可用 |
| 20 MiB 上限靠分块搬运中止实现，实现错了会先吃内存 | 测试直接送一个超限的流式 body，断言 413 且没有落盘 |
| 内容寻址 + 跨主体共享 blob，删除时会有悬空引用 | M3 不删除（D11），因此不存在这个问题；将来加删除时必须同时加引用计数 |
| 前端上传是二进制的 multipart，与既有的 JSON 接口风格不同 | `web/lib/api.ts` 新增一个专用函数，不复用 JSON 那条路径；走查真实上传一个 PDF 并断言库里有它 |
| `python-multipart` 是新依赖 | 用户已批准；`make api-install` 与 CI 安装命令不变，`pyproject.toml` 加一行 |
| CI 跑不了前端走查（Playwright 只在本地借兄弟仓库，见 `.github/workflows/ci.yml` 末尾） | 前端批次的可视证据只在本地生成（截图 + `make verify` 输出）；PR 描述里必须写明"CI 未覆盖走查" |
| `scope` 与 `check_type` 的取值只在 Python 里约束的话，手写 SQL 能塞进非法值 | 加数据库 CHECK 约束，并用"插入非法行被拒"的测试钉住，与既有 `test_programs_api.py` 钉 `source_id` 的做法一致 |

### 测试清扫：要改的是清扫函数，不只是 fixture 的顺序

这是本 change 最容易把 `make verify` 弄红的地方，单独写一段。

`api/tests/conftest.py` 的 session 级 fixture 在**收集第一个测试之前**就会调用 `clear_the_roadmap_definition`，而这个函数（conftest.py:50-90）正是删 Genuine Student `sources` 行的那个。新的 `review_criteria.source_id` 是 RESTRICT，所以只要要点还在，这个删除就会以 `review_criteria_source_id_fkey` 失败，整个测试运行在第一个测试之前就红了。把顺序写进 fixture 的 teardown 解决不了这件事——**要改的是 `clear_the_roadmap_definition` 本身**：先删 findings、再删 criteria，然后才轮到 source。

第二处同类问题在 ORM 一侧：`document_reviews.version_id` 与 `document_versions.document_id` 都是 NOT NULL 的外键。SQLAlchemy 默认会在删父行之前把子行的外键置空，这会在 NOT NULL 上直接报错，而数据库的 `ON DELETE CASCADE` 根本来不及生效。`api/app/models/roadmap.py:23-25` 已经记过同一个坑。因此这几个关系要显式声明 `passive_deletes=True`，或者清扫时逐层显式删除；两者选一个并写进测试。

测试的存储根通过 monkeypatch 指向 `tmp_path`，不写进开发目录；`clients` 的清扫仍靠数据库级联（D12 的 CASCADE）。

## Migration Plan

1. `make db-up && make migrate`：一条新迁移建 5 张表。既有表不动，因此不存在数据回填。
2. 新迁移必须能从空库一次建全，也要能 `alembic downgrade -1` 干净回退（父设计 §8.1）：`downgrade` 按依赖倒序 drop，并先 drop D7 那条 `use_alter` 的外键。
3. `make seed`：`seed_cli.py` 在既有路线图种子之后调用 `seed_review_criteria`（幂等）。Genuine Student 的 `sources` 行由 `seed_roadmap` 建立，要点种子复用它，不另建一条 URL 重复的行。
4. 回滚：`alembic downgrade -1` 删表即可；磁盘上的 blob 目录留着不影响任何东西（没有表指向它）。
5. 部署：M3 不改变部署方式。文件存储是本地目录，线上（Vercel）不可用——这是既有已知限制，不在 M3 解决。

## Open Questions

1. 线上存不了文件：一是没有持久磁盘，二是 Vercel 的函数请求体上限约 4.5 MB，20 MiB 的上传在那里连后端都到不了（[Vercel KB](https://vercel.com/kb/guide/how-to-bypass-vercel-body-size-limit-serverless-functions)）。把后端从 Vercel 挪走、或改成客户端直传对象存储，二者必居其一——不在 M3 范围，但 M3 之后这条路必须有人走。
2. `roadmap_tasks.document_id` 这一列现在既不写、也没人读：`documentId` 只声明在 wire 类型上（`web/lib/roadmap-source.ts:90`），`toTaskRows` 不映射它，也没有任何组件读它。要不要在下一批删掉，还是让它将来承担"一条要求的最新归档材料"？——D13 先让它保持 NULL。
3. `documents.program_id` 同样恒为 NULL（D13）。若按项目索引材料成了真实需求，再启用它，并且那时要想清楚它与 `task_id` 谁说了算。
4. 审核结论现在只有维护者能写，界面上申请人只能读。真正的产品形态里"谁审"（中介？顾问？）尚未确定——M4 引入 agent 之后需要重新回答。
5. Genuine Student 之外的材料类型（成绩单、PS、推荐信）的审核要点还没有核验过的官方来源，因此 M3 只有 `gs` 要点可用，护照类材料在 M3 里审不了（见 D9）。`general` 与其余 scope 的要点归"数据标注"里程碑。
