# Session handoff

**唯一的当前状态文件。会话结束时覆盖，开始时读，并先对照 `git status` 和 `git log`。**

## 现在在哪

- 2026-10-29。**11 月 1 日开始投递**（agent 开发 + 后端岗），本项目是面试作品集
- 项目名：鱼跃彼岸 / LeapAshore（数据库用户名、库名、卷名仍是 `offerpilot`，故意不改，改了线上数据卷会丢）
- 线上：<http://43.161.224.82>（腾讯云香港），**跑的还是改名前的版本，没重新部署**
- 域名 `mortyyjt.site` 在等实名审核；通过后 `@` → 个人网站，`yuyue` → 本项目，Caddy 按域名分流 + HTTPS
- 开发工具改用 Cindy（makecindy/cindy，底层跑 Claude Code / Codex），多 agent 分工规则已删

## 规则从哪读

- 需求：`docs/product/PRD.md`，和其他文件冲突时以它为准
- 工程规则：`AGENTS.md`（+ `docs/engineering/agent-guidelines.md`）；`CLAUDE.md` 只是引用它
- 跨 change 的决定：`note/decisions.md`；想法池：`note/product/backlog.md`
- 后端设计：`note/design/`；材料库现行规格：`openspec/specs/`

## 已决定、待做（按顺序）

1. **原型重做**（走 OpenSpec）：选校组合、申请路线图（主界面）、材料库按原型样式重做并接后端；
   测评从 `/api/profile` 读背景（不再读 sessionStorage）；顾问后台 / 联系顾问先从导航隐藏；
   做完删旧界面（`AppShell` `FlowView` `HomeView` `MaterialsView` `ProfileView` `SettingsView`
   `PortfolioPicker` `Generating`、`lib/store.ts` 等）、旧走查 `scripts/e2e-walkthrough.cjs` 与
   `docs/screenshots/01…29`、6 个占位项目的镜像校验（`web/lib/programs.ts` + 两个 check 脚本）
2. 重新部署（改名后的版本）；域名审核过后上 HTTPS
3. 热门学校真实录取要求（官网来源，状态"机器核对"，人工核验才写 `verified_at`）
4. 注册登录：先不做

## 验证状态

- 后端 213 条、前端 205 条通过（2026-10-29，本地 Docker Postgres，新库要先 `make migrate` + `make seed`）
- `make verify` 的走查一步测的是旧界面，见清理 PR 里的结果

## 怎么跑与部署

- 本地：`make dev` / `make test` / `make verify`
- 部署（仓库根目录）：rsync 到 `ubuntu@43.161.224.82:~/offerpilot/`（排除 node_modules、.next、.venv、
  .git、.env、deploy/.env、api/var、docs/screenshots），然后在服务器上
  `cd ~/offerpilot/deploy && sudo docker compose -f compose.prod.yaml up -d --build`
- 服务器密钥在服务器的 `~/offerpilot/deploy/.env`，不进库

## 坑

- 流式响应要自己写 cookie：返回 `StreamingResponse` 时必须调 `set_client_cookie`
- LangGraph `interrupt` 前不能有写操作：恢复时整个节点从头重跑
- 新访客可能还没有 `clients` 行：写组合前先 `load_or_create_profile`
- 对话存在 `InMemorySaver`，API 重启即丢；换 Postgres checkpointer 是 schema 变更，要先问
- 仓库本地 git 身份必须是 `MortyYJT` + noreply 邮箱（曾被设成 `rehearsal`）
- 公开仓库历史已于 10-28 改写去掉真名；已合并 PR 页面仍引用旧提交
