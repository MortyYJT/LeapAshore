# Session handoff

**This is the only current-state file. Overwrite it at the end of a session; read it at the start.**
Verify it against `git status` and `git log` before trusting it.

## Where we are

- 日期：2026-10-28；**11 月 1 日开始投递**（岗位：agent 开发 + 后端），本项目是面试作品集
- 分支：`claude/deploy-mvp`（从 `codex/static-prototype` 的 `ea2c91a` 切出），已提交并推送，PR 待合并
- 线上：<http://43.161.224.82>（腾讯云香港，Ubuntu 24.04，2 核 3.6G + 4G swap），已在跑
- **正在等**：用户买的域名 `mortyyjt.site` 实名审核。通过后用户加 A 记录（`@` 与 `yuyue` → `43.161.224.82`）并放行安全组 443

## 本次会话做了什么

- **PRD**：`docs/product/PRD.md`（中文）。已定：D1 两套前端合并、D5 覆盖范围 = 学校库 346 所（QS 2027 前 300 + 46 所地区补齐）、
  分档去掉"信息不足"（未知项改为表单必填 + 项目侧"要求待采集"）。未定：D2、D3
- **部署**：`deploy/compose.prod.yaml`（db / api / web / caddy）、`deploy/Caddyfile`（`/api/*` → FastAPI，其余 → Next）、
  `api/Dockerfile`（启动时跑迁移和幂等种子）、`web/Dockerfile`（`NEXT_OUTPUT=standalone`）。服务器密钥在 `~/offerpilot/deploy/.env`（不进库）
- **顾问 agent**：`api/app/agent/`，移植自用户自己的 MEWHELP（LangGraph）。分意图 → 问官方要求走检索 + 证据门禁（拒答记知识缺口日志）→
  ReAct（步数封顶）→ 改档案直接写、改选校组合 `interrupt` 等确认。接口 `api/app/routers/advisor.py`（SSE）。
  模型：DeepSeek 官方（`CHAT_BASE_URL=https://api.deepseek.com`，`CHAT_MODEL=deepseek-chat`）
- **前端**：`AdvisorView` 接流式 agent（意图/门禁/工具标签、来源列表、确认卡片），`/prototype/advisor` 改用它
- **网站入口**：`/` 只保留首次引导问卷；填完 → `/prototype/assess/result`（背景经 `web/lib/prototype-handoff.ts` 写入原型的 sessionStorage）；
  cookie `offerpilot_onboarded=1` + `web/proxy.ts` 让回访直接进 `/prototype`。旧主界面（选校组合、路线图）不再可达
- **README** 重写（英文，含架构图与 agent 图）

## 验证状态

- 后端：全量 213 条通过（2026-10-28，新建库后先 `make migrate` + `make seed`）
- 前端：`npm test` 205 条通过，`next build` 通过
- 线上端到端（curl + 浏览器）：问要求带来源 ✅、未收录学校拒答 ✅、写档案 ✅、改组合确认后落库 ✅、重复确认被拒 ✅、首访问卷 → 原型带背景 ✅、回访跳转 ✅
- 引导问卷 10 步没有在浏览器里手动点完（代码未改）

## 已决定、待执行

- **改名已完成**：中文「鱼跃彼岸」、英文 LeapAshore，cookie / 存储键 / 包名 / 响应头全改。**数据库用户名、库名、卷名仍是 `offerpilot`**（改了线上数据卷会丢）。GitHub 仓库 `MortyYJT/offerpilot` 尚未改名
- **域名**：`mortyyjt.site` 放个人网站，`yuyue.mortyyjt.site` 放本项目。GitHub 用户名保持 MortyYJT（`guyuy` 已被占）
- **个人网站**：本地已删，用 GitHub 上 `MortyYJT/MortyYJT.github.io` 的静态构建（源码 `personal-website-guyuy`），Caddy 按域名分流
- 注册登录先不做；背景仍只存在 sessionStorage

## 下一步

0. 前端改版 + 注册登录（用户 10-28 提出，待设计）
2. 域名审核通过 → Caddyfile 改成两个站点块（自动 HTTPS）、compose 暴露 443、服务器上 clone 个人网站静态构建、更新 README 线上地址
4. 热门学校真实录取要求：先几所，带官网来源，状态"机器核对"，人工核验后才写 `verified_at`

## 已知限制

- 对话存在 `InMemorySaver`，API 重启即丢；换 Postgres checkpointer 是 schema 变更，要先问
- 知识缺口只写日志（logger `offerpilot.knowledge_gap`），没有后台队列
- 只有 HTTP；没有评测集
- 旧限制仍在：测试偶发红（`applications_client_id_fkey` 等，既有问题，见 `note/product/backlog.md`）、`test_sources.py` 泄漏一行

## 怎么跑与部署

- 本地：`make dev` / `make test`。本会话的 venv 用的是 `../offerpilot/.runtime-tools/` 下的 uv 建的 `api/.venv`
- 部署（从仓库根目录）：
  `rsync -az --exclude node_modules --exclude .next --exclude .next-build --exclude .venv --exclude api/var --exclude .git --exclude .runtime-tools --exclude .npm-cache --exclude .env --exclude deploy/.env --exclude docs/screenshots -e "ssh -i ~/.ssh/offerpilot_codex -o IdentitiesOnly=yes" ./ ubuntu@43.161.224.82:~/offerpilot/`
  然后 `ssh ... 'cd ~/offerpilot/deploy && sudo docker compose -f compose.prod.yaml up -d --build'`
- 看日志：`sudo docker compose -f compose.prod.yaml logs api --since 5m`

## 坑

- **流式响应要自己写 cookie**：FastAPI 只把依赖里 `Response` 的头合并进它自己构造的响应；返回 `StreamingResponse` 时必须调用 `set_client_cookie`，否则每条消息都是新访客
- **interrupt 前不能有写操作**：恢复时整个节点从头重跑
- **新访客可能还没有 `clients` 行**：任何写组合的路径先 `load_or_create_profile`
- interrupt 的载荷自带 `type`，SSE 事件里要把 `type` 放在最后，免得被覆盖
- 不要把模型密钥发给它所属以外的服务商（试过被安全规则拦下）
