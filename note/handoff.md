# Session handoff

**This is the only current-state file. Overwrite it at the end of a session; read it at the start.**
Verify it against `git status`, `git log` and `gh pr list` before trusting it.

## Where we are（2026-10-10）

- `main` 仍是 M3 合入后的 `794a911`。今天的工作都在 PR 里，**等 MortyYJT 合并**：
  - PR #13 `claude/workflow-v2`：装开发流程 v2 + guard hook；`note/decisions.md`（今天全部决定及理由）；
    愿景 / 路线图 / 想法池按新定位重写；本文件
  - PR #14 `dsh/interview-m1-m3`：M1–M3 中文复盘和题目（dsh 写，`note/interview/`），不阻塞
  - PR #16 `codex/static-prototype`：10 页静态原型（`/prototype`），关 issue #15
- **产品定位已变**：OfferPilot 是 MortyYJT 留学中介的获客与初筛工具（见 `note/product/vision.md`）
- **当前阶段**：静态原型定功能点 → 原型定稿后再拆后端、排期。之前的 S1–S5 草案**未批准**，排期作废
- M4（会话与提案）已移进想法池；分支 `dsh/stage-2-m4-conversations` 保留

## 分工（v2）

MortyYJT 决策 + 合并；Claude 调研、出方案、派活、审查、推送、开 PR；Codex 按 issue 在独立 worktree
里实现；dsh 出题。阻塞关口只有「批准方案」和「合并 PR」。所有决定连同理由写进 `note/decisions.md`。

## 下一步

1. MortyYJT 看原型（PR #16 的截图在 `docs/screenshots/prototype/`，或本地 `cd web && npm run dev` 打开 `/prototype`），
   提出要增删改的功能点
2. 原型定稿后：把已定的后端决定（CRICOS 骨架、三档核验、官方页采集 + Claude API 抽取、规则分档、
   留资与转人工）拆成 OpenSpec change，排期，派给 Codex
3. 原型合并后，按 dispatch 第 7 步给 dsh 派出题（提示词开头写【offerpilot · Stage 原型：静态原型】）

## 待用户回答

- `.git/config` 的本地身份是占位的 `rehearsal <rehearsal@example.com>`（main 上已有 3 个提交用了它）；
  要不要改回 `MortyYJT` + noreply。本会话每次提交都用 `git -c user.name=... -c user.email=...` 绕过
- 是否在 GitHub 设置里隐藏个人邮箱（网页合并的 merge commit 用的是个人邮箱）
- 原型示例门槛偏高：典型 211 / 78 / 雅思 6.5 的背景全部「不满足」，要不要调低示例门槛让演示更好看

## 坑

- Codex 沙箱：worktree 里提交不了（要 `--add-dir "$(git rev-parse --git-common-dir)"`，未实测）；
  不能联网（先 `cp -Rc` 复制 `web/node_modules`）；不能监听端口（浏览器走查由 Claude 做）
- dsh 会话：`~/.dsh/sessions/<path>/` 下带 `session-` 前缀的才是对话，纯 UUID 是子 agent
- `scripts/e2e-walkthrough.cjs` 写死了能认出机主的绝对路径（既有问题，已开 chip 任务）
- 端口 3000 有另一个项目；原型验证用的是 `next start -p 3015`
- 其余旧坑（测试偶发红、合批次用 merge commit、conftest 清扫）见 git 历史里上一版 handoff（`794a911`）

## 怎么跑

- `make dev` → `make verify`；只看前端：`cd web && npm test && npm run build`
- 工作树：`../offerpilot-workflow-v2`（PR #13）、`../offerpilot-prototype`（PR #16）；合并后可删
