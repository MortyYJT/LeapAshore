# Session handoff

**This is the only current-state file. Overwrite it at the end of a session; read it at the start.**
Verify it against `git status` and `git log` before trusting it.

## Where we are

- 日期：2026-10-08
- OpenSpec change：`stage-2-m3-document-library`（`openspec validate` 通过）
- 两个 PR **已开、未合并**，等用户：
  - 后端 [#8](https://github.com/MortyYJT/offerpilot/pull/8)，分支 `dsh/stage-2-m3-document-library-backend`
  - 前端 [#9](https://github.com/MortyYJT/offerpilot/pull/9)，分支 `dsh/stage-2-m3-document-library-frontend`（基于 #8，等 #8 合并后会自动变干净）
- `main` 仍是 `10b1fb6`，本会话没有动过

## 做了什么（tasks.md 第 1–7 组）

- 后端：5 张表与迁移；材料的上传 / 版本 / 归档 / 送审 / 下载接口（按 cookie 隔离，别人的材料一律 404）；
  内容寻址存储、按魔数判类型、20 MiB 两处限流、下载路径限制在存储根内、版本号在行锁下取；
  10 条 Genuine Student 要点种入（全部 `待核验`）；维护者 CLI `api/review_cli.py`（全仓库唯一写 `verified_at` 的地方）
- 前端：材料适配层（对照两份真实响应体）、五个接口调用、`MaterialsView` 材料库页、`材料库` 标签、
  任务行上传入口；未知一律 `未知` / `未分类`，不编造分类或结论
- 证据：后端 200 用例、前端 175 用例、`make verify` 退出码 0、走查 29 张截图全绿
- 验证文档：`docs/verification/stage-2-m3-document-library-{backend,frontend}.md`
- 计划：`note/superpowers/plans/2026-10-08-stage-2-m3a-document-library-backend.md`

## 还没做

- tasks.md 第 8 组剩下的两项：**合并后** `openspec archive stage-2-m3-document-library`；
  合并后把 M3 从 roadmap 的"待合并"移进"已完成"
- 工作区无未提交改动（除 4 张截图，见下）

## 已知问题

- **测试偶发红，属既有问题**：症状是某行在用例还需要它时消失（`applications_client_id_fkey` 等）。
  证据：`main` 的 worktree 上、把 M3 的表降级掉之后，单跑 `test_applications_api.py` 六次仍有两次失败。
  记在 `note/product/backlog.md` 与后端验证文档第 3 节。
- `test_sources.py` 每次运行泄漏一行 `sources`（既有）
- 开发库里有一批遗留匿名 `clients`（本会话的探针、审查与走查留下的），没有删

## 下一步（M4）

按 `note/product/roadmap.md` 第 2 项开新的 OpenSpec change：会话、消息、提案（agent 写操作待确认）。
M3 留下的接口在这里要用到：`document_reviews` 现在只由 CLI 写，M4 的 agent 送审要接上
（design.md D10 记了 `run_id` 推迟到 M4 加）。

## 怎么跑

- `make dev`（同时起数据库、:8000 的 API、:3000 前端）→ `make verify`（检查命令，CI 跑同样的步骤）
- 后端单跑 `make api-test`；CLI `cd api && .venv/bin/python review_cli.py --help`

## 坑

- 端口 3000 上跑着**用户另一个项目**的 dev 服务器（IPv4）；本项目的 next dev 绑 IPv6 :3000，
  `localhost:3000` 解析到 `::1` 才是本项目。若 `make dev` 报 "Port 3000 is in use"，那是它；
  若报 "Another next dev server is already running" 且进程已死，删掉 `web/.next/dev/lock` 即可
  （本会话遇到过一次；`web/.next` 的 Turbopack 缓存坏掉时也报 AMQF 反序列化失败，删掉整个 `.next` 重启）
- git 的**仓库本地**身份是公开 handle + GitHub noreply（原来的真实姓名与个人邮箱不符合
  `docs/engineering/agent-guidelines.md`）；全局配置未动
- 测试直接跑在共享开发库上；`conftest` 的清扫会删掉路线图定义、GS 来源与要点并在收尾还原
  （还会把人工核验过的 `status`/`verified_at` 快照还原），改它之前先读它的 docstring
