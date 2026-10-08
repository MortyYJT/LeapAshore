# Session handoff

**This is the only current-state file. Overwrite it at the end of a session; read it at the start.**
Verify it against `git status` and `git log` before trusting it.

## Where we are

- 日期：2026-10-08
- 分支：`dsh/stage-2-m3-document-library-backend`，已推送，**PR #8 已开、未合并**（等用户）
- `main` 仍是 `10b1fb6`（本次会话没有动过 main）
- OpenSpec change：`stage-2-m3-document-library`；`openspec validate` 通过

## 本次会话做了什么（后端批次 = tasks.md 第 1–6 组）

- 新建 5 张表与迁移：`documents`、`document_versions`、`review_criteria`、`document_reviews`、`document_review_findings`
- 材料库接口：上传、加版本、列表、详情、下载、归档、送审；全部按 cookie 隔离，别人的材料一律 404
- 上传服务：内容寻址存储、按魔数判类型（DOCX 还要是含 `word/document.xml` 的 zip）、20 MiB 两处限流、版本号在行锁下取
- 审核依据：种入 10 条 Genuine Student 要点（全部 `待核验`、`verified_at` 留空），`GET /api/review-criteria` 只读
- 维护者 CLI `api/review_cli.py`：核验/退回要点、写入带 `criterion_id` 的审核结论；**全仓库唯一写 `verified_at` 的地方**
- 证据：`make verify` 退出码 0（200 后端用例、25 张走查截图、无 JS 错误、四个守卫全过）
- 验证文档：`docs/verification/stage-2-m3-document-library-backend.md`
- 实施计划：`note/superpowers/plans/2026-10-08-stage-2-m3a-document-library-backend.md`

## 还没做

- **PR 2（前端）**：材料库视图、任务行上传入口、走查新增步骤与截图 —— tasks.md 第 7 组
- 收尾（tasks.md 第 8 组）：`note/product/roadmap.md` 标 M3 完成、合并后 `openspec archive`
- 工作区里仍有 4 个 `docs/screenshots/*.png` 的改动，**不是本次会话产生的**，没有提交

## 已知问题

- **测试偶发红，属既有问题**：症状是某行在用例还需要它时消失（`applications_client_id_fkey` 等）。
  证据：在 `main` 的 worktree 上、把 M3 的表降级掉之后，单跑 `test_applications_api.py` 六次仍有两次失败。
  记在 `note/product/backlog.md` 与验证文档第 3 节；恢复 schema 后连跑十二次全绿。
- `test_sources.py` 每次运行泄漏一行 `sources`（既有，已记 backlog）

## 下一步（PR 2）

1. 从 `dsh/stage-2-m3-document-library-backend` 切 `dsh/stage-2-m3-document-library-frontend`
2. 按 tasks.md 第 7 组：`MaterialsView` + `AppShell` 入口 + `FlowView` 任务行上传；`page.tsx` 建 `material_key → task id` 映射
3. 走查脚本新增步骤（上传真实 PDF → 归档 → 送审 → 重载仍在）并截图
4. `make verify` + 独立审查 + 开 PR 2

## 怎么跑

- `make dev`（同时起数据库、:8000 的 API 与 :3000 前端）→ `make verify`（检查命令，CI 跑同样的步骤）
- 后端单跑：`make api-test`；CLI：`cd api && .venv/bin/python review_cli.py --help`

## 坑

- 端口 3000 上还跑着**用户另一个项目**的 dev 服务器（IPv4）；本项目的 next dev 会用 IPv6 绑 3000，
  `localhost:3000` 解析到 `::1` 才是本项目。若 `make dev` 报 "Port 3000 is in use"，那是它。
- 本会话已把 git 的**仓库本地**身份设为公开 handle + GitHub noreply（原来的真实姓名与个人邮箱不符合
  `docs/engineering/agent-guidelines.md`）；全局配置未动。若要回退：`git config --local user.name/user.email`。
- 测试直接跑在共享开发库上；`conftest` 的清扫会删掉路线图定义与 GS 来源并在收尾还原，
  改动清扫顺序前先读它的 docstring。
