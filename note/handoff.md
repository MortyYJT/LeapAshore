# Session handoff

**当前状态文件。每次会话结束时覆盖；开始时先读，并对照 `git status` 和 `git log`。**

## 现在（2026-10-30）

- 规则已收成一份 `CLAUDE.md`；任务清单是根目录的 `TASKS.md`，按顺序做。
- 个人网站 mortyyjt.site 已修复（PR #28，10-30 部署，只重建了 caddy 容器）。
- 下一步：`TASKS.md` P0 第二条「按新范围收缩学校库」。
- 线上运行的是 main（截至 PR #30），地址 https://leapashore.mortyyjt.site 。
- 生产库（10-29）：programs 7586，`verified_at` 非空 0。上次部署前的备份在服务器 `~/db-backup-20261029-pre-frontend.sql.gz`。
- `make verify` 自 PR #29 之后没有重跑；`TASKS.md` P0 里有这一项。

## 开放问题

- **GitHub 合并会写入 MortyYJT 的私人邮箱**：在 GitHub 网页或 `gh pr merge` 合并时，提交者字段用的是账号主邮箱。要 MortyYJT 在 GitHub → Settings → Emails 勾选「Keep my email addresses private」。已推送的历史不改写。
- 采集数据里需要人工确认的点写在各校 json 的 `notes` 里（旧清单可在提交 `1a9fa30` 的 handoff 里查到）。
- 截止日期会过期：10-29 时已有 139 条早于当天。截止日期入库后，界面要按当天日期标「已截止」，不能当成未来日期排时间线。
- Commons 上 CC BY / CC BY-SA 的校徽需要在界面上署名（`logo_license`、`logo_source` 已在 fixture 里），学校库页面还没有署名区。
- 被拦的学校（按规则不绕过）：Monash、Melbourne、Macquarie、NUS 大部分、Oxford 主站、UCL（50 个后 403）、Bristol、Durham、Bath、Cardiff、York（16 个后 429）、QUB、Stanford 计算机系。

## 部署

- 服务器：`ubuntu@43.161.224.82`，SSH 加 `-i ~/.ssh/offerpilot_codex -o IdentitiesOnly=yes`（ssh-agent 里没有这把钥匙）。
- 部署前先在服务器上用 `pg_dump` 备份生产库到 `~/db-backup-<日期>.sql.gz`。
- 同步代码：本机 `git archive origin/main` 导出，再 `rsync --delete` 到服务器 `~/offerpilot/`，保留 `deploy/.env`、`deploy/*.bak-*`、`api/var/`。然后在服务器上 `cd ~/offerpilot/deploy && sudo docker compose -f compose.prod.yaml up -d --build`。
- 导入采集数据：把本机快照的元数据 json 临时拷进 api 容器，导完立即删除（里面的 `text_path` 含本机路径，导入器不读它）。
- 上线后只做只读检查（状态码、页面无报错）。完整走查不要对线上跑：它的清理只删本机库的数据。
- 密钥在服务器 `~/offerpilot/deploy/.env`，不进库。
- 主域名 `mortyyjt.site` 和 `www` 是个人网站，由本服务器的 Caddy 托管，文件在 `/srv/mortyyjt.site`，由个人网站仓库的 GitHub Actions 上传（钥匙被 rrsync 限制在该目录）。`deploy/Caddyfile` 末尾两段站点配置和 compose 里的 `/srv/mortyyjt.site` 挂载属于个人网站，别删；部署前确认 main 的 Caddyfile 里还有它们，否则个人网站会挂。
- 只改 Caddy 配置时，只重启 caddy：`sudo docker compose -f compose.prod.yaml up -d --force-recreate --no-deps caddy`（不加 `--force-recreate` 时，只改 Caddyfile 内容 compose 不会重建容器，rsync 换掉的新文件也不会进到旧容器的单文件挂载里）。

## 坑

- Turbopack dev 缓存会继续给旧 CSS：删掉 `web/.next` 再重启 dev。`make clean` 会删 `node_modules`。
- 本机 API 不带 `--reload`，加了新路由要重启 uvicorn。
- 返回 `StreamingResponse` 时必须调用 `set_client_cookie`，否则流式响应不带 cookie。
- Playwright 自带的 Chromium 截中文会截掉半个字，截图要用 `channel: 'chrome'`。
- 跑 `test_seed.py` 会把 5 个占位项目重置成种子版本；要看导入效果，就重跑 importer。
- 本机 macOS 证书库缺 HARICA 2021 根证书，快照工具在装了 certifi 时会用它；不要关掉证书校验。
