# M3 测试指引（醒来直接照这个走）

日期：2026-10-08。M3（材料库 + 审核依据）已合并进 `main`，下面是已经起好、可以直接点开的状态。

## 现在正在跑的东西

| 东西 | 地址 | 说明 |
| --- | --- | --- |
| 前端 | <http://localhost:3001> | **用这个地址**。绑在 3001 是为了避开你另一个项目占着的 3000（那个在 IPv4 上，本项目之前绑 IPv6，`localhost:3000` 你到底会看到哪个取决于解析顺序） |
| API | <http://127.0.0.1:8000/api/health> | 前端通过自己的 `/api/*` 代理访问它，cookie 同源，所以不用配 CORS |
| 数据库 | Docker 容器 `offerpilot-db-1`，端口 55432 | 已 seed：6 个项目、7 个阶段、33 条材料要求、10 条 GS 审核要点 |

我离开前用完整走查在这个地址上跑过一遍：材料的上传 / 分类 / 归档 / 送审 / 下载 / 审核结论渲染全部通过，无 JS 错误（`EXIT=0`）。

## 五分钟走一遍材料库

1. 打开 <http://localhost:3001>，把 onboarding 走完（或直接用你浏览器里已有的状态）。
2. 进「流程进度」，随便点一个阶段，比如「学术与身份材料」。
3. 每条材料右边有「**上传材料**」——选一个 PDF / PNG / JPEG / DOCX（≤ 20 MB）。
4. 切到「**材料库**」标签：能看到刚才那份材料，徽章是 `未分类` + `待归档`。
   - 注意：归档按钮在你没选分类时是**灰的**；下拉框默认是「请选择分类」。这是刻意的——之前的实现会默认成"成绩单"，等于替你做了一个分类决定。
5. 选一个分类（想看审核就选「Genuine Student 陈述」），点「归档」→ 徽章变「已归档」。
6. 点「送审」→ 徽章变「审核中」。
7. 点「查看审核」→ 面板会说「还没有审核结论」。**它不会编一条出来**，这是要确认的一半。
8. 点「下载」→ 拿回来的就是上传时那份文件（字节一致）。

## 审核结论这条路（只有 CLI 能写，这是设计）

这个仓库没有登录也没有角色，所以"标记要点已核验"和"写入审核结论"都不开 HTTP 接口——否则任何访问者都能做。它们走维护者命令：

```bash
cd api

# 1. 找出你要审的那份材料的 id（新加的子命令）
.venv/bin/python review_cli.py list

# 2. 写一条审核结论（--version 必须是你刚看的那一版，写错会被拒）
.venv/bin/python review_cli.py review <上面列出的 id> \
  --version 1 --overall needs_revision --reviewed-by 我 \
  --summary "回答需要补充" \
  --finding "gs-answer-length:warning:第二条回答 213 词，超过 150 词"
```

回到浏览器**刷新**，进「材料库」→「查看审核」，应当看到：结论、审阅人、建议正文，以及建议下面两行——
**依据：回答长度（gs-answer-length）** 与 **来源：Genuine Student requirement（待核验）**，来源是一个可点的官方链接。
这就是产品的核心主张：每条建议都能回溯到官方页面。

顺带可以试掉之前没验证过的分支：

```bash
cd api
.venv/bin/python review_cli.py verify-criterion gs-answer-length   # 把要点标成「已核验」
.venv/bin/python review_cli.py unverify-criterion gs-answer-length
```

标成已核验后再刷新，「来源」后面的状态会变成「已核验」——这条渲染分支在 M3 的走查里看不到（种子里没有已核验的要点），正好由你补上。**记得跑完 unverify 退回**，否则它会一直显示已核验。

## 值得故意试的几种"应该被拒绝"

- 上传一个 `.pdf` 但内容是文本的假文件 → 415，提示只接受四种格式。
- 上传超过 20 MB 的文件 → 413。
- 没归档就直接点「送审」→ 按钮本来就是灰的；用 API 直接打会得到 409。
- 审核时 `--overall pass` 却给一条 `blocker` 建议 → 拒绝；`needs_revision` 却一条建议都不给 → 也拒绝。
- 用别人的材料 id 调接口 → 一律 404（不是 403，避免泄露 id 是否存在）。

## 建议重点试的地方（这些是审查里风险最高的几处）

1. **连点两次写操作**：在「材料库」里快速点两次「上传新版本」，或一次归档还没回来就点送审。
   期望：第二次会看到"上一次材料操作还在进行中，请稍候再试。"，而不是两个结果互相覆盖。
   （这是审查报的 should-fix，修法是加了一把真正的互斥锁，不是靠 `disabled`——`disabled` 会晚一帧生效。）
2. **接近上限的文件**：19 MB 的 PDF 应当成功，21 MB 应当 413 且 `api/var/documents` 下不留文件。
3. **假 DOCX**：把一个 `.zip` 改名成 `.docx` 上传 → 415（服务端会打开压缩包找 `word/document.xml`）。
4. **同一份文件传两次**：两份材料会指向**同一个** blob 文件（内容寻址去重）。可以直接看：
   `find api/var/documents/blobs -type f | wc -l` 与材料数量的关系。
5. **下载后再打开**：下载回来的文件应当能正常打开，`Content-Type` 是服务端判定的类型（不是浏览器按扩展名猜的那个）。
6. **审核结论的边界**：`--overall pass` 配一条 `blocker` 建议会被拒；`needs_revision` 不给建议也会被拒；
   引用一条 `gs` 要点去审一份 `transcript` 材料也会被拒（要点有范围）。

## 检查命令

```bash
make verify                                   # 需要前端在 3000 上（走查默认打那个地址）
BASE_URL=http://localhost:3001 make verify    # 用现在这个环境跑，等价
```

`make verify` = 构建 + 前端类型检查与单测（175）+ 四个守卫 + 后端测试（200）+ 真实浏览器走查（29 张截图）。
当前 `main`（`48ea7e3`）上它是 `EXIT=0`。

## 想改代码时看哪里

| 想改 | 文件 |
| --- | --- |
| 上传规则（类型 / 大小 / 存储路径 / 版本号） | `api/app/services/documents.py` |
| 归档与送审的状态机 | 同上，`ARCHIVE_ALLOWED_FROM` / `SUBMIT_ALLOWED_FROM` |
| 路由与主体隔离 | `api/app/routers/documents.py` |
| 审核结论的规则（建议必须引用要点等） | `api/app/services/reviews.py` |
| 维护者命令 | `api/review_cli.py` |
| 审核要点种子（10 条 GS 骨架） | `api/app/seed_review_criteria.py` |
| 前端适配与文案 | `web/lib/materials-source.ts` |
| 材料库界面 | `web/components/MaterialsView.tsx` |
| 任务行上传入口 | `web/components/FlowView.tsx` |

当前事实的 spec 在 `openspec/specs/{document-library,document-review,review-criteria}/spec.md`（26 条需求）；
这次 change 的 proposal / design / tasks 在 `openspec/changes/archive/2026-10-08-stage-2-m3-document-library/`。

## 已知限制（别以为是 bug）

- **没有删除功能**：材料、版本、文件都不能删（M3 的决定，等 M4 的确认机制）。
- **审核结论只能由 CLI 写**，界面上只能读。
- **线上不可用**：存储根是本地目录，而且 Vercel 的函数请求体上限约 4.5 MB，20 MB 的上传在线上到不了后端。M3 只在本地可用。
- **护照类材料现在审不了**：只有 `gs` 范围的要点有核验过的官方来源。
- 走查和你的测试会在 `api/var/documents` 留下文件（主体删了、文件不删）。

## 收工 / 重开

```bash
# 停
kill $(lsof -t -iTCP:3001 -sTCP:LISTEN) $(lsof -t -iTCP:8000 -sTCP:LISTEN)
make db-down

# 重开
make dev          # 数据库 + API(8000) + 前端(3000)
# 或者只要 3001：
make db-up && make api-dev-bg && (cd web && npx next dev -p 3001)
```

坑：`make dev` 若报 "Another next dev server is already running" 而进程其实已死，删掉 `web/.next/dev/lock` 再来。
