# Session handoff

**当前状态文件。每次会话结束时覆盖；开始时先读，并对照 `git status` 和 `git log`。**

## 现在（2026-10-30）

- 规则已收成一份 `CLAUDE.md`；任务清单是根目录的 `TASKS.md`，按顺序做。
- 个人网站 mortyyjt.site 已修复（PR #28，10-30 部署，只重建了 caddy 容器）。
- 学校库已收缩到范围内 287 所（PR #34）：29 个国家和地区，日本 8 所采集文件已删。
- **范围内采集统计（10-30 重算，「仓库清理」直接用）**：133 所有采集文件，其中 120 所有项目（13 所 0 项目：被拦或连不上），共 5,223 个项目，5,163 个 `机器核对`、60 个 `待核验`；学校库里还有 154 所未采。README 和 PRD 已改成这组数。重算命令见 `TASKS.md` 该条。
- 账号与登录（PR #36）：邮箱 + 6 位验证码登录，服务端会话，`/assess` 删掉换成登录弹窗里的信息页，分档页搬到 `/tiers`，隐私政策草稿 `/privacy`。设计和匿名合并规则见 `openspec/changes/account-login/design.md`（change 还没归档，tasks.md 是进度清单）。**生产登录模式没开**（`AUTH_ENABLED` 未设），行为和以前一样是匿名 cookie；开之前要 MortyYJT 配 SES，见下面「切到登录模式」。
- 本机 `make api-dev-bg` 默认开登录模式，验证码写到 `api/var/mail.log`（不发信）；走查要求后端在登录模式，否则直接退出并说明。
- 下一步：`TASKS.md` P0 第四条「修顾问检索：先测基线，再改」。
- 线上运行的是 main（截至 PR #36 合并，10-30 部署，登录模式关；生产库已用 `remove_schools --apply` 删掉日本 8 所），地址 https://leapashore.mortyyjt.site 。个人网站 https://mortyyjt.site 也由这里的 Caddy 出。
- 生产库（10-30，PR #34 部署后）：programs 7496（删日本 8 所前 7586），范围外国家项目 0，`verified_at` 非空 0。最近一次部署前的备份在服务器 `~/db-backup-20261030-pre-auth.sql.gz`（PR #36 前；Alembic 现在是 `4aa9ab68bed6`）。
- `make verify`（PR #36，10-30）：后端 394、前端 232、走查 106/106（本机登录模式）。

## 开放问题

- **登录模式等 MortyYJT 配发信（卡在本人）**：步骤见「部署 → 切到登录模式」。隐私政策 `/privacy` 是 AI 草稿，要 MortyYJT 审核正文、补联系方式。
- 生产顾问用的是 `api.deepseek.com` 的 `deepseek-chat`（服务器 `deploy/.env`），不是 TASKS.md 写的硅基流动 DeepSeek-V4-Flash；隐私政策按生产实际写的 DeepSeek。下一条改顾问时留意。

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
- 上线后只做只读检查（状态码、页面无报错）。注意匿名模式下 `GET /api/profile` 会建一个匿名主体，检查别打它，或者打完按 id 删掉。完整走查不要对线上跑：它的清理只删本机库的数据。
- 密钥在服务器 `~/offerpilot/deploy/.env`，不进库。
- 主域名 `mortyyjt.site` 和 `www` 是个人网站，由本服务器的 Caddy 托管，文件在 `/srv/mortyyjt.site`，由个人网站仓库的 GitHub Actions 上传（钥匙被 rrsync 限制在该目录）。`deploy/Caddyfile` 末尾两段站点配置和 compose 里的 `/srv/mortyyjt.site` 挂载属于个人网站，别删；部署前确认 main 的 Caddyfile 里还有它们，否则个人网站会挂。
- **切到登录模式**（MortyYJT 配好之后，任何一个 agent 都可以做）：
  1. MortyYJT：腾讯云控制台开通「邮件推送 SES」（服务器在中国香港地域，SMTP 用 `smtp.qcloudmail.com:465`；如果 SES 开在广州地域则是 `gz-smtp.qcloudmail.com`）。新建发信域名，建议用子域 `mail.mortyyjt.site`（别用主域名，免得和主域名其他邮件记录冲突）。
  2. MortyYJT：在 DNSPod 给 `mortyyjt.site` 加记录（值以 SES 控制台「发信域名 → 验证」页面显示的为准，DKIM 公钥每个域名不同，只能从控制台复制）：SPF——主机 `mail`、TXT、`v=spf1 include:qcloudmail.com ~all`；DKIM——主机形如 `xxx._domainkey.mail`、TXT、`v=DKIM1; k=rsa; p=…`（控制台给）；DMARC——主机 `_dmarc.mail`、TXT、`v=DMARC1; p=none`；控制台若列了 MX 记录也照抄。等 10 分钟左右，在控制台点「验证」，状态变「验证通过」。
  3. MortyYJT：SES 控制台新建发信地址 `noreply@mail.mortyyjt.site`，给它设 SMTP 密码（不需要建邮件模板，代码直接发正文）。
  4. 填服务器 `~/offerpilot/deploy/.env`（模板见 `deploy/.env.example`）：`AUTH_ENABLED=true`、`MAIL_BACKEND=smtp`、`SMTP_HOST`、`SMTP_PORT=465`、`SMTP_USER=noreply@mail.mortyyjt.site`、`SMTP_PASSWORD=…`、`MAIL_FROM=鱼跃彼岸 <noreply@mail.mortyyjt.site>`。
  5. `sudo docker compose -f compose.prod.yaml up -d --force-recreate --no-deps api`；`docker compose logs api` 里没有 `AUTH_ENABLED=true in production needs a real mail backend` 才算启动成功。用自己的邮箱在网站上登录一次，确认收到信（看一下是不是进了垃圾箱）。
  6. 加 90 天清理的 cron（`crontab -e`，用服务器本地时间）：`17 3 * * * cd ~/offerpilot/deploy && sudo docker compose -f compose.prod.yaml exec -T api python -m app.cleanup --apply >> ~/cleanup.log 2>&1`。先手动跑一次不带 `--apply` 的看报告。
  7. 回滚：删掉 `.env` 里的 `AUTH_ENABLED=true` 再重建 api，回到匿名模式；表可以留着。
- 只改 Caddy 配置时，只重启 caddy：`sudo docker compose -f compose.prod.yaml up -d --force-recreate --no-deps caddy`（不加 `--force-recreate` 时，只改 Caddyfile 内容 compose 不会重建容器，rsync 换掉的新文件也不会进到旧容器的单文件挂载里）。

## 坑

- 登录后、退出登录后不要用 `router.push("/")`：客户端路由可能缓存了登录状态下预取的 `/`，而 proxy 对它的回答是跳 `/roadmap`。退出登录用整页跳转（`window.location.assign`）。
- 后端测试默认是匿名模式（`AUTH_ENABLED` 代码默认关），登录模式的测试用 `tests/auth_helpers.py` 的 `login_mode` fixture 打开，验证码从 `outbox` 拿，不发信。
- 本机 dev server（:3000）的 Turbopack 缓存会给旧 CSS，登录弹窗会贴在左上角；对 `make build` 产物走查不会。

- Turbopack dev 缓存会继续给旧 CSS：删掉 `web/.next` 再重启 dev。`make clean` 会删 `node_modules`。症状之一：走查「390：导航收进菜单」失败。dev server 不是自己起的、不方便重启时，可对 `make build` 产物走查：`cd web && NEXT_DIST_DIR=.next-build npx next start -p 3100`，再 `BASE_URL=http://localhost:3100 node scripts/walkthrough.cjs`。
- 从数据库删学校用 `python -m app.collect.remove_schools [--apply] <university_id>...`，不要手敲 SQL；被选校组合、材料或路线图任务引用的项目会保留并列在 `kept_programs`。
- 本机 API 不带 `--reload`，加了新路由要重启 uvicorn。
- 返回 `StreamingResponse` 时必须调用 `set_client_cookie`，否则流式响应不带 cookie。
- Playwright 自带的 Chromium 截中文会截掉半个字，截图要用 `channel: 'chrome'`。
- 跑 `test_seed.py` 会把 5 个占位项目重置成种子版本；要看导入效果，就重跑 importer。
- 本机 macOS 证书库缺 HARICA 2021 根证书，快照工具在装了 certifi 时会用它；不要关掉证书校验。
