# Session handoff

**This is the only current-state file. Overwrite it at the end of a session; read it at the start.**
Verify it against `git status` and `git log` before trusting it.

## Where we are

- 日期：2026-10-08
- `main` = M3 全部合入（后端 PR #8、前端 PR #9、归档 PR #10、审查命令 PR #11），M3 的 spec 已归档
- **要测试就照 `note/testing-m3.md` 走**：前端已起在 <http://localhost:3001>（避开你另一个项目的 3000），
  API 在 :8000，数据库已 seed；那份指引里的每条命令我都跑过一遍
- `openspec/specs/` 现在是 current truth：`document-library`(13) / `document-review`(8) /
  `review-criteria`(5)，共 26 条需求
- 归档件：`openspec/changes/archive/2026-10-08-stage-2-m3-document-library/`（proposal / design / specs / tasks，
  58 项全部勾完）
- 路线图里 M3 已从待办移进"已完成"，下一个是 M4

## 本次会话交付了什么

- 后端：5 张表与迁移；材料的上传 / 版本 / 归档 / 送审 / 下载接口（按 cookie 隔离，别人的材料一律 404）；
  内容寻址存储、按魔数判类型、20 MiB 两处限流、下载路径限制在存储根内、版本号在行锁下取；
  10 条 Genuine Student 要点种入（全部 `待核验`）；维护者 CLI `api/review_cli.py`（全仓库唯一写 `verified_at` 的地方）
- 前端：材料适配层（对照两份真实响应体）、五个接口调用、`MaterialsView` 材料库页、`材料库` 标签、
  任务行上传入口
- 证据：后端 200 用例、前端 175 用例；`make verify` 在**合并后的 main 上**退出码 0，29 张走查截图，无 JS 错误
- 验证文档：`docs/verification/stage-2-m3-document-library-{backend,frontend}.md`（后者第 7 节是 26 条需求
  到代码与检查的对应表）
- 两轮独立审查的问题全部修完。前端那个 blocker 值得记：分类下拉框默认"成绩单"，点一次归档就把未分类的
  材料写成了成绩单——已改成"请选择分类"且未选时按钮不可点

## 还没做

- 没有部署过。线上有两个已知限制：存储根是本地目录；Vercel 函数请求体上限约 4.5 MB，20 MiB 上传到不了后端
- "来源已核验"的渲染分支没在浏览器里出现过（种子里没有已核验的要点）
- 走查的材料库步骤会在 `api/var/documents` 留下孤儿 blob（主体清理了、文件不删，是 D11 的决定）

## 已知问题

- **测试偶发红，属既有问题**：症状是某行在用例还需要它时消失（`applications_client_id_fkey` 等）。
  证据：`main` 的 worktree 上、把 M3 的表降级掉之后，单跑 `test_applications_api.py` 六次仍有两次失败。
  记在 `note/product/backlog.md` 与后端验证文档第 3 节
- `test_sources.py` 每次运行泄漏一行 `sources`（既有）
- 开发库里有一批遗留匿名 `clients`（本会话的探针、审查与走查留下的），没有删

## 下一步（M4）

按 `note/product/roadmap.md` 第 1 项开新的 OpenSpec change：会话、消息、提案（agent 写操作待确认）。
M3 留下的接口在这里要用到：`document_reviews` 现在只由 CLI 写，M4 的 agent 送审要接上
（`openspec/specs/document-review/spec.md` 与归档的 design.md D10 记了 `run_id` 推迟到 M4 加）。

## 怎么跑

- `make dev`（同时起数据库、:8000 的 API、:3000 前端）→ `make verify`（检查命令，CI 跑同样的步骤）
- 后端单跑 `make api-test`；CLI `cd api && .venv/bin/python review_cli.py --help`
- 归档：`openspec archive <change>`；`openspec list` 看活跃 change

## 坑

- 端口 3000 上跑着**用户另一个项目**的 dev 服务器（IPv4）；本项目的 next dev 绑 IPv6 :3000，
  `localhost:3000` 解析到 `::1` 才是本项目。若 `make dev` 报 "Port 3000 is in use"，那是它；
  若报 "Another next dev server is already running" 且进程已死，删掉 `web/.next/dev/lock` 即可
  （本会话遇到过一次；`web/.next` 的 Turbopack 缓存坏掉时报 AMQF 反序列化失败，删掉整个 `.next` 重启）
- **合并两个批次时用 merge commit**：预演过，squash #8 之后再合 #9 会在 `note/handoff.md`、
  `note/product/backlog.md`、`tasks.md` 三个文件上冲突
- git 的**仓库本地**身份是公开 handle + GitHub noreply（原来的真实姓名与个人邮箱不符合
  `docs/engineering/agent-guidelines.md`）；全局配置未动
- 测试直接跑在共享开发库上；`conftest` 的清扫会删掉路线图定义、GS 来源与要点并在收尾还原
  （还会把人工核验过的 `status`/`verified_at` 快照还原），改它之前先读它的 docstring
