# Session handoff

**当前状态文件。每次会话结束时覆盖；开始时先读，并对照 `git status` 和 `git log`。**

## 现在（2026-10-30）

- 规则已收成一份 `CLAUDE.md`；任务清单是根目录的 `TASKS.md`，按顺序做。
- 个人网站 mortyyjt.site 已修复（PR #28，10-30 部署，只重建了 caddy 容器）。
- 学校库已收缩到范围内 287 所（PR #34）：29 个国家和地区，日本 8 所采集文件已删。
- **范围内采集统计（10-30 重算，「仓库清理」直接用）**：133 所有采集文件，其中 120 所有项目（13 所 0 项目：被拦或连不上），共 5,223 个项目，5,163 个 `机器核对`、60 个 `待核验`；学校库里还有 154 所未采。README 和 PRD 已改成这组数。重算命令见 `TASKS.md` 该条。
- 账号与登录（PR #36）：邮箱 + 6 位验证码登录，服务端会话，`/assess` 删掉换成登录弹窗里的信息页，分档页搬到 `/tiers`，隐私政策草稿 `/privacy`。设计和匿名合并规则见 `openspec/changes/account-login/design.md`（change 还没归档，tasks.md 是进度清单）。**生产登录模式没开**（`AUTH_ENABLED` 未设），行为和以前一样是匿名 cookie；开之前要 MortyYJT 配 SES，见下面「切到登录模式」。
- 本机 `make api-dev-bg` 默认开登录模式，验证码写到 `api/var/mail.log`（不发信）；走查要求后端在登录模式，否则直接退出并说明。
- 顾问检索（PR #38）：校名按数据识别（繁简折叠、英文名、括号缩写、简称表 `api/data/advisor/university_aliases.json`），学科按 `Program.field`（`api/data/advisor/subjects.json`），门槛要求项目有录取要求数据，筛选在 SQL 里（新索引 Alembic `5c1e7f0a2b3d`），拒答文案按计数生成。评估集和跑法在 `api/evals/`（`python -m evals.run_advisor`）；**报数组 30 条已在最终代码上跑过一次，以后别再拿它调参**——P1「混合检索」要用它重跑对比时照实记录即可。CI 的 `advisor-eval` 任务只跑调参组。
- 顾问限流与额度（PR #40）：Redis 滑动窗口（主体 + IP）和每日 token 上限（主体、IP、全站 200 万；放行时预扣、结束时按实际用量结算），超限 429、Redis 连不上 503（fail-closed）；`max_tokens` 放请求体（DeepSeek 忽略 `max_completion_tokens`）；IP 只在对端是 `TRUSTED_PROXIES`（生产 `caddy`）时读 `X-Forwarded-For`。设计 `openspec/changes/advisor-limits/`，压测 `python -m evals.load_advisor_limits`。默认数字是估的，待 MortyYJT 复核。
- 抽取（PR #42）：`python -m app.collect.extract <school_key> <sha256> [--name …]`（在 `api/` 下）用顾问的模型把一份快照抽成采集文件格式的一个项目，预检 + `verify` 后不过的值删掉、原因进 `rejected`；只打印，不写文件。测量 `python -m evals.extract_rejection --per-school 10`（要 `CHAT_*` 指向 DeepSeek，见下面「开放问题」第二条；花约 1 元），10-30 结果：10 所 95 页拒收率 10.3%，结果文件 `api/evals/results/extract-2026-10-30.json`。离线工具，没部署。
- 仓库清理（PR #43）：删了 4 处移植说法和一处本机路径，加了 MIT LICENSE；README/PRD 的截止日期写成「已采集、未入库」（79 所、2,335 个项目、3,986 条）。P1 第一条里的 4,055 / 4,874 是删日本前的数，现在是 3,986 条截止日期、4,831 个带学术要求的机器核对项目。
- 限流超时撤回（PR #44，10-30 部署，只重建 api）：放行回复超时时撤回本次放行，503 不再留下 8,000 token 预扣。部署前备份 `~/db-backup-20261030-pre-withdraw.sql.gz`。
- 「有要求」口径统一（PR #46，10-30 部署 api + web）：生产库「带要求的项目 4,389 个」（删日本前；删后 4,383）和本机 5,163 不一样是口径不同，不是导入过期——生产库和采集文件逐项一致，没重新导入。现在只有一个口径 `has_requirement_data()`（`api/app/models/program.py`：英语、985/211 均分、其他院校均分、先修课之一），项目库筛选、学校库计数、顾问门槛共用；前端项目表和详情页用同规则的 `statesARequirement`（`web/lib/catalog.ts`），改一处要两处一起改。生产 4,815（部署前备份 `~/db-backup-20261030-pre-stated.sql.gz`，只重建 api 和 web）。三个数的含义：5,163 = 采集文件里机器核对、已入库的项目；4,813 = 其中详情页能显示要求的；4,815 = 4,813 + 2 个手填占位。查询见 `TASKS.md` 该条。
- **P0 全部做完**（只剩卡在 MortyYJT 本人的部分，见下面「卡在 MortyYJT」）。
- 截止日期和学术要求入库（P1 第一条，PR #48）：Alembic `b7d4e2a91c60` 加 `programs.academic_requirement`、`programs.academic_source_url` 和表 `program_deadlines`；导入器写过了 `verify` 的学术要求摘要和截止日期，重跑不改任何行。截止日期**不写进** `applications.official_deadline`（那是组合行自己记的日期）；`GET /api/applications` 的 `program.deadlines` 带上项目的截止日期，前端 `web/lib/deadlines.ts` 的 `deadlineOf` 决定显示哪个（组合行自己的 > 下一轮 > 全部已过的标「已截止」> 未收录），「今天」按北京时间在渲染时算。「有要求」口径加了学术要求和截止日期（后端 `has_requirement_data`、前端 `statesARequirement`、顾问评估 `evals/run_advisor.py` 的相关集，三处一起改）。本机：3,986 条截止日期、4,831 个学术要求、「有要求」5,161。设计 `openspec/changes/requirement-dates/`（未归档）。
- 截止日期入库已部署（10-30，只重建 api 和 web）：部署前备份服务器 `~/db-backup-20261030-pre-deadlines.sql.gz`，Alembic 现在是 `b7d4e2a91c60`；生产数和本机一致（3,986 / 4,831 / 「有要求」5,161 / 已截止 130）；用户的组合行和路线图行部署前后整表 md5 相同（记录在服务器 `~/pre-deadlines-user-dates.txt`）。
- 采集队列（P1 第二条，第一阶段代码 PR #50）：Celery + Redis，每页一个任务，状态在新表 `collect_pages`，要求变化记 `requirement_changes`（Alembic `6afe86aaf7b6`）。设计 `openspec/changes/archive/2026-10-30-collect-queue/`（已归档；tasks.md 是进度清单和 Run log）。本机跑法：`make worker`（或 `api/var/work/start-worker.sh`，带 DeepSeek 配置），`python -m app.collect.queue status|discover|enqueue|resume|export`（在 `api/` 下）。队列**不写目录库**：`export` 写回采集文件 → 审阅提交 → 原导入器入库。
- 补采（P1 第二条第二阶段，PR #51）：`_schools.json` 扩到 287 所（带 `listing_urls`）；队列补采 118 所 3,628 个项目（2,262 个机器核对），模型费 36.37 元（上限价）。采集文件现在 248 所、238 所有项目、8,851 个项目、7,425 个机器核对；本机导入后「有要求」7,421、截止日期 4,776 条。细节和 Run log 在 `openspec/changes/archive/2026-10-30-collect-queue/tasks.md`。
- 补采的审查和生产入库（PR #52，10-30 部署）：审查 PR #51 找到 3 个问题已修（细节见 `TASKS.md` 该条和归档的 collect-queue tasks.md Run log）：澳洲学校只导到 CRICOS 行上（没有 CRICOS 代码的跳过，宁缺不重）；新 `app/collect/tidy.py` 清掉列表页、本科等非项目页和名字里的 CSS/卡片文字（发现、队列、`export` 都会用，改已提交的文件用 `python -m app.collect.tidy --apply`，只动队列采的项目）。采集文件现在 248 所、234 所有项目、8,783 个项目、7,376 个机器核对。**生产已入库**，和本机一致：「有要求」7,310、截止日期 4,722 条 / 2,728 个项目 / 119 所、学术要求 6,806、`verified_at` 非空 0。生产 beat 的第一次重采在 10-31 04:07（北京），在那之前 `collect_pages`、`requirement_changes` 都是空的。
- 第二轮采集（PR #54，10-30 导入生产）：39 所没有文件的学校由 Claude 子代理采（MortyYJT 指示，本机采集一律用子代理、不调 DeepSeek；生产 beat 仍用 DeepSeek），16 所采到 252 个项目（每校最多 20 个，文件里 `complete: false` + `remaining_urls`，以后可接着采）。现在采集文件 282 所、250 所有项目、9,035 个项目、7,611 个机器核对；生产「有要求」7,545、截止日期 4,763 条、学术要求 7,039。P1 第二条「采集队列 + 变更检测」全部做完，openspec change 已归档（`openspec/changes/archive/2026-10-30-collect-queue/`，Run log 在那里的 tasks.md）。
- 对话持久化（P1 第三条，PR #56）：顾问的对话从内存换到 PG（`langgraph-checkpoint-postgres==3.2.0`，`api/app/agent/checkpoint.py`），表由 Alembic `c4e8a1d2f6b9` 建（`checkpoint_migrations`、`checkpoints`、`checkpoint_blobs`、`checkpoint_writes`，不调库的 `setup()`）。线程 id 仍是 `{主体}:{对话 id}`。确认（`/confirm`）按线程拿 PG advisory lock、重读暂停状态、按中断 id 续上；每轮结束剪到最新一个存档。注销/90 天匿名清理在同一事务里删对话，登录合并时搬对话，beat 每天 03:17 删 90 天没动的对话（匿名模式也删）。设计 `openspec/changes/archive/2026-10-30-advisor-persistence/`（已归档，spec 在 `openspec/specs/advisor-persistence/`）。**10-30 已部署**：部署前备份 `~/db-backup-20261030-pre-checkpoints.sql.gz`，Alembic 现在是 `c4e8a1d2f6b9`；生产跑过 1 轮真实顾问，重启 api 后确认卡仍在（生产没点确认，写入只写一次是本机测的），测试线程已删。
- **下一步：P1 第四条「混合检索」**（报数组 h08 标签要先照实改，见「开放问题」）。
- 线上（10-30）已跑 PR #40：compose 多了 `redis` 容器；部署前备份在服务器 `~/db-backup-20261030-pre-limits.sql.gz`（Alembic 仍是 `5c1e7f0a2b3d`，PR #40 没改表）。
- 线上运行的是 main（截至 PR #38 合并，10-30 部署，登录模式关；生产库已用 `remove_schools --apply` 删掉日本 8 所），地址 https://leapashore.mortyyjt.site 。个人网站 https://mortyyjt.site 也由这里的 Caddy 出。
- 生产库（10-30，PR #34 部署后）：programs 7496（删日本 8 所前 7586），范围外国家项目 0，`verified_at` 非空 0。最近一次部署前的备份在服务器 `~/db-backup-20261030-pre-retrieval.sql.gz`（PR #38 前；Alembic 现在是 `5c1e7f0a2b3d`）。
- `make verify`（P1 第一条，10-30，审查修复后）：后端 505、前端 245、走查 120/120（新加 14 项截止日期检查：下一轮实心带来源、全部已过标「已截止」且不画、组合行自己的日期优先、项目页列出）。:3000 dev server 删了 `web/.next` 重起过，:8000 API 重起过（登录模式）。

## 卡在 MortyYJT（P0 汇总，10-30）

1. **开登录模式**：开通腾讯云 SES、DNSPod 加发信域名记录（SPF/DKIM/DMARC）、建发信地址并把 SMTP 账号密码填进服务器 `deploy/.env`。步骤见「部署 → 切到登录模式」第 1–3 步；之后任何 agent 都能做第 4–7 步。
2. **审核隐私政策** `/privacy`（AI 草稿）正文，补联系方式。
3. **GitHub 邮箱隐私**：Settings → Emails 勾选「Keep my email addresses private」，否则合并提交会带私人邮箱。
4. **复核 AI 自主决定**（`note/decisions.md` 里标「待 MortyYJT 复核」的各条），主要是：顾问限流默认额度和 Redis 挂了就 503；顾问门槛「只有 CRICOS 课程名不算证据」是否太严、简称表、评估集标签；抽取器多条学术路线只留第一条；README 数据条款措辞和 QS 转载授权；两个手填占位项目要不要删（见下）。

## 开放问题

- 两个手填的 `待核验` 占位项目（`api/app/seed.py`：`cricos-103000K` Monash 人工智能、`cricos-111671D` 悉尼计算机）仍算「有要求」：英语一栏是「需同时满足 Monash 英语要求」这类指引，均分 60/65 是早期手填、没过 `verify`。待 MortyYJT 决定是否删掉这些手填值（删要连 `test_seed.py` 一起改）。
- 学术要求和截止日期入库后（PR #48），机器核对项目里只剩 4 个界面上看不到任何要求：都只有不带分数的语言说明（Emory 数学、芝加哥 2 个、USC 1 个；芝加哥的雅思只有单项 7.0、没有总分，导入器 `english_text` 只写有总分的）。只有说明文字的语言要求和中国学生要求要不要显示、怎么措辞，还没定。

- **登录模式等 MortyYJT 配发信（卡在本人）**：步骤见「部署 → 切到登录模式」。隐私政策 `/privacy` 是 AI 草稿，要 MortyYJT 审核正文、补联系方式。
- 生产顾问用的是 `api.deepseek.com` 的 `deepseek-chat`（服务器 `deploy/.env`），不是 TASKS.md 写的硅基流动 DeepSeek-V4-Flash；隐私政策按生产实际写的 DeepSeek。10-30 跑意图评估时 DeepSeek 返回的模型名是 `deepseek-flash`（价格页已不列 `deepseek-chat`，旧名仍可调用）。本机评估用的是 shell 里的 `DEEPSEEK_API_KEY`：`CHAT_BASE_URL=https://api.deepseek.com CHAT_MODEL=deepseek-chat CHAT_API_KEY="$DEEPSEEK_API_KEY"`。
- **待 MortyYJT 复核（顾问限流）**：默认额度（主体 10 次/分钟、60 次/小时；IP 30 次/分钟、200 次/小时；每天每主体 20 万、每 IP 60 万、全站 200 万 token）；Redis 挂了顾问就 503 是否可接受。改数字只要改服务器 `deploy/.env`（变量名见 `deploy/.env.example`）再重建 api。
- **待 MortyYJT 复核（顾问检索）**：简称表是否地道；门槛「只有 CRICOS 课程名不算证据」是否太严（本机 31 所学校因此对要求问题全部拒答，如墨尔本、麦考瑞）；评估集标签是 AI 标的。

- **GitHub 合并会写入 MortyYJT 的私人邮箱**：在 GitHub 网页或 `gh pr merge` 合并时，提交者字段用的是账号主邮箱。要 MortyYJT 在 GitHub → Settings → Emails 勾选「Keep my email addresses private」。已推送的历史不改写。
- NTU 8 个托福 1–6 新分制的值（PR #48 起）显示为「TOEFL iBT 4.5（新版 1–6 分制）」：导入器按 `scale: "iBT 1-6"` 加注，采集文件没改。
- 抽取器的已知局限：`verify` 只保证引文逐字在页上、数字在引文里，`text`/`label`/`recommended` 是否忠实没查；同温度 0 下截止日期的拒收数在跑与跑之间能差一倍（模型时而从页面别处推年份）。
- 采集数据里需要人工确认的点写在各校 json 的 `notes` 里（旧清单可在提交 `1a9fa30` 的 handoff 里查到）。
- 截止日期会过期（10-30 按北京时间 130 条已过）：界面在渲染时按当天判断、标「已截止」，库里不存状态。最晚的一条是 2028-02-01，随着时间推移越来越多项目会变成「全部已截止」，要靠 P1「采集队列」定期重采。
- Commons 上 CC BY / CC BY-SA 的校徽需要在界面上署名（`logo_license`、`logo_source` 已在 fixture 里），学校库页面还没有署名区。
- **Crawl-delay**（10-30 起遵守）：82 个已缓存的 robots.txt 写了 5–120 秒，快照工具以前一律 2 秒；补采时 13 个站点被按 2 秒抓了（数据保留，见 decisions）。
- （10-30 第二轮已做，见上；现在还没采到项目的是 37 所，多数被拒，规则不允许绕过。下面是第二轮之前的记录。）补采后还没采到项目的 49 所：10 所有文件但被拒（见下一条），39 所没有文件——10 所没找到列表页，其余是列表页被拒、渲染超时或页面上没有项目链接。第二轮找列表页没做（会话的网页搜索额度用完），下一个有搜索额度的 agent 可以接着做：把新 URL 写进 `_schools.json` 的 `listing_urls`，`python -m app.collect.queue discover <key>...`，worker 跑完 `export`。
- 队列采的 1,366 个项目页没有要求通过核对（多数学校把入学要求写在另一页，队列只读项目页本身），在文件里是 `待人工`、不入库。
- 顾问评估报数组 h08（悉大建筑）标签和库不一致（PR #48 学术要求进口径后就有），`--split heldout` 会拒绝打分；P1「混合检索」用报数组前要先照实改标签。
- 被拦的学校（按规则不绕过）：Monash、Melbourne、Macquarie、NUS 大部分、Oxford 主站、UCL（50 个后 403）、Bristol、Durham、Bath、Cardiff、York（16 个后 429）、QUB、Stanford 计算机系。

## 部署

- 对话持久化（PR #56）的部署只是普通的「备份 → 同步代码 → `up -d --build`」：api 容器启动时 `alembic upgrade head` 建四张 checkpoint 表。部署那一刻正在等确认的对话（还在内存里）会丢最后一次。看对话数：`sudo docker compose -f compose.prod.yaml exec -T db psql -U offerpilot -d offerpilot -c "select count(distinct thread_id) from checkpoints"`（库名、用户以 `deploy/.env` 为准）。手动跑 90 天对话清理：`... exec -T api python -m app.cleanup --conversations-only`（加 `--apply` 才删）。

- 服务器：`ubuntu@43.161.224.82`，SSH 加 `-i ~/.ssh/offerpilot_codex -o IdentitiesOnly=yes`（ssh-agent 里没有这把钥匙）。
- 部署前先在服务器上用 `pg_dump` 备份生产库到 `~/db-backup-<日期>.sql.gz`。
- 同步代码：本机 `git archive origin/main` 导出，再 `rsync --delete` 到服务器 `~/offerpilot/`，保留 `deploy/.env`、`deploy/*.bak-*`、`api/var/`。然后在服务器上 `cd ~/offerpilot/deploy && sudo docker compose -f compose.prod.yaml up -d --build`。
- 导入采集数据（PR #52 起的做法）：快照元数据 tgz 解到 api 容器里一个单独目录（如 `/app/var/importmeta`），用一个临时脚本调 `import_school(session, data, schools, root=<那个目录>/snapshots)` 逐个文件导入（写成文件 `scp` 再 `docker cp` 进去跑，不要从 ssh 的标准输入喂给 `docker compose exec`），**不加 `--prune`**（会删掉 3 个早先导入、没有 CRICOS 代码的 Curtin 项目），导完删 tgz、脚本、解包目录。下面是 PR #48 时的旧做法，供参考。旧做法：把本机快照的元数据 json 临时拷进 api 容器，导完立即删除（里面的 `text_path` 含本机路径，导入器不读它）。做法（PR #48 部署时用的）：本机 `cd api/var && tar czf <tmp>/snapmeta.tgz --exclude='_*' $(cd snapshots && find . -name '*.json' -not -name '_*' | sed 's#^#snapshots/#')`，`scp` 到服务器，`sudo docker cp` 进 `deploy-api-1:/app/var/`，`sudo docker compose -f compose.prod.yaml exec -T api sh -c 'cd /app/var && tar xzf snapmeta.tgz && cd /app && python -m app.collect.importer'`，然后在容器里 `rm -rf /app/var/snapshots /app/var/snapmeta.tgz`、服务器上删 tgz。
- 改表的部署：api 容器启动时自己跑 `alembic upgrade head`（`api/Dockerfile`），所以备份 → 同步代码 → `up -d --build` 就完成迁移；之后再按上一条导入。
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
- 采集队列（PR #50 起）：生产 compose 多了 `worker`（`--pool threads --concurrency 2`）和 `beat`（只能有一个），快照在命名卷 `snapshots`（`/app/var/snapshots`），beat 调度文件在卷 `beat-data`。beat 每天 04:07（北京）重采 30 天没采过的页面（默认每天 200 页、模型费 1 元，`deploy/.env` 里 `COLLECT_*` 可调），03:17 跑 90 天匿名清理（只在 `AUTH_ENABLED=true` 时删，所以「切到登录模式」第 6 步的 cron 不用加了）。看进度：`sudo docker compose -f compose.prod.yaml exec -T worker python -m app.collect.queue status --budget daily:$(TZ=Asia/Shanghai date +%F)`。要把生产发现的变化入库：容器里 `python -m app.collect.queue export --out /app/var/snapshots/_export`，`docker cp` 出来对比仓库里的文件，审阅、提交、按上面的导入步骤导入。生产镜像没 Chrome，要渲染的页面在生产记 `deferred`。
- compose 里有 `redis` 服务（顾问限流，P1 Celery 复用），数据卷 `redis-data`；api 依赖它健康才启动。Caddyfile 改了的部署，`up -d --build` 之后还要单独 `up -d --force-recreate --no-deps caddy`（见下一条）。看今天的用量：`sudo docker compose -f compose.prod.yaml exec redis redis-cli --scan --pattern 'leapashore:tokens:site:*'` 再 `GET` 对应键。
- 只改 Caddy 配置时，只重启 caddy：`sudo docker compose -f compose.prod.yaml up -d --force-recreate --no-deps caddy`（不加 `--force-recreate` 时，只改 Caddyfile 内容 compose 不会重建容器，rsync 换掉的新文件也不会进到旧容器的单文件挂载里）。

## 坑

- 顾问对话的表（PR #56 起）：后端测试要先 `make migrate`（`alembic upgrade head`），否则顾问相关测试报表不存在。conftest 的 `remove_the_conversations_these_tests_create` 按线程 id 清掉测试写的对话。升级 `langgraph-checkpoint-postgres` 时，`test_alembic_carries_every_migration_of_the_pinned_library` 会在库多了迁移时失败：把新迁移抄进一个新的 Alembic revision（只加不删），再改 `checkpoint.MIGRATIONS_APPLIED` 和 `MIGRATIONS_DIGEST`。
- 顾问的 checkpointer 是同步 `PostgresSaver` + 线程（不是 `AsyncPostgresSaver`）：异步版绑死创建时的事件循环，测试客户端每个请求一个循环，会坏。它自己的连接池最多 2 个连接（`CHECKPOINT_POOL_SIZE`），每个进行中的确认另占 1 个短连接（advisory lock）。
- zsh 里 `"$SUB:restart1"` 的 `:r` 会被当成修饰符（去扩展名），拼线程 id 要写 `"${SUB}:restart1"`。

- Celery worker 在 macOS 上必须 `--pool threads`（prefork 在 Python 3.12/macOS 是 spawn，任务一跑就 `ValueError: not enough values to unpack`）。生产也用 threads，保持一致。快照工具的文件写入（robots 缓存、拒绝名单、快照）因此都改成了加锁 + 原子替换。
- 采集队列的 broker 是 Redis 1 号库（`CELERY_BROKER_URL`），顾问计数在 0 号库；清空队列用 `celery -A app.worker purge -f`，别 `FLUSHALL`。
- 拒绝记录（`api/var/snapshots/_blocked_hosts.json`）新条目带时间、30 天后过期；10-30 之前的旧条目是纯字符串、永久有效，要重试只能人手删那一行。

- 后端测试要 Redis（`make db-up` 现在同时起 db 和 redis，本机端口 56379）；没起时顾问相关测试会 503 失败。每个测试用自己的键前缀（conftest 的 `isolate_the_advisor_limits`），结束时删掉；这个清理 10-30 有一次在 redis-py 的握手里抛了 `AttributeError`（不可复现），已改成一并吞掉。
- 抽取器测试回放 `api/tests/fixtures/extract/response.json`（对虚构页面录的真实响应）；改了 `ProgramRequirements` 的结构就要重录：对 `page.html` 调一次真实 API，把原始响应体存下来（录制脚本没进库，思路是给 `ChatOpenAI` 传带 response hook 的 `httpx.Client`）。
- `get_chat_model` 的输出上限必须走 `extra_body={"max_tokens": …}`：LangChain 的 `max_tokens` 字段发出去是 `max_completion_tokens`，DeepSeek 不认（实测）。
- 顾问的限流在 endpoint 里、请求体校验通过之后才查（不要改回 `Depends`：依赖先于校验运行，422 也会占名额、预扣也不会还）。一轮对话在后台任务（`advisor._detached`）里跑完，结束时 `limits.settle` 归还预扣；新加花钱的路径要拿 ticket 并保证 settle。`check` 超时会先撤回本次放行（`_WITHDRAW`，按放行 id 幂等）再抛 `LimitsUnavailable`，所以 503 不会留下预扣；改 `_CHECK` 的 KEYS/ARGV 顺序时两个脚本一起改。

- 顾问的学科名称模式（`subjects.json` 的 `name`）在 PostgreSQL 里跑，别写 `\b`（PG 里是退格），用 `(^|[^a-z])…([^a-z]|$)`。改简称表后跑 `python -m evals.run_advisor --split tune`：它会检查每个 id 都在库里、标签和库一致。
- 本机 :3000 的 dev server 若是很早起的旧进程，`/assess` 会 404、走查 28/30；对 `make build` 产物走查即可（见下一条）。

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
