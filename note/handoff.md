# Session handoff

**当前状态文件。每次任务结束整份重写，不追加；开始时先读，并对照 `git status` 和 `git log`。历史看 git 和 `note/decisions.md`。**

## 现在（2026-10-31）

- **线上：** <https://leapashore.mortyyjt.site> 跑 main 到 PR #80（10-31 北京时间 02:30 左右部署），**匿名模式**（`AUTH_ENABLED` 未设）。Alembic `c8e1f4a7b2d9`；最近一次部署前备份 `~/db-backup-20261031-pre-site-polish.sql.gz`（服务器日期；#79、#80 没有迁移），服务器上只留最近 3 份备份。库是 `pgvector/pgvector:pg16`、卷 `deploy_pgdata`（`C` 排序），角色和库名 `leapashore`。项目目录 `~/leapashore`，compose 项目名仍是 `deploy`。换 pgvector 前的旧卷 `deploy_db-data` 和镜像 `postgres:16-alpine` 已删。个人网站 mortyyjt.site 也由这台的 Caddy 出。
- **服务器 SSH（10-31）：** 只认密钥，密码登录和 root 登录都关了；fail2ban 已开（5 次失败封 1 小时）。细节和解封命令见 `docs/deploy.md`。没检查腾讯云安全组的 22 端口来源限制。
- **生产数据：** 「有要求」7,374，`机器核对` 4,115，截止日期 3,555 条（1,947 个项目、111 所，10-30 北京时间已过 289 条），`sources.verified_at` 非空 0，快照 9,345 页、132,208 块；近几次部署前后用户的组合和路线图表整表 md5 不变。beat 第一次重采在 10-31 04:07（北京），在那之前 `collect_pages`、`requirement_changes` 是空的。
- **本机采集文件：** 282 所、250 所有项目、9,035 个项目；忠实度回填后机器核对 4,162，还有 125 个项目和中国学生要求 2,278 条没判（DeepSeek 余额已恢复，回填是单独一项、还没做，见下面「待做」）。
- **产品站收尾（10-31，已部署）：** PR #79 标签页图标（`/icon.svg`、`/favicon.ico`、`/apple-icon.png`）；PR #80 删掉 `/programs` 列表（线上 404），学校详情页按项目名和方向筛选（在页面里筛，不用 API 的 `q`，因为它也匹配校名），项目详情只列有值的要求，去掉「未核对」「自动标注」等内部字样和每页底注，全站一行页脚署名（QS、CRICOS CC BY 2.5 AU、3 枚 CC BY-SA 校徽、隐私政策），路线图没填入学时间时只给一句话和按钮，加载占位，首页示例路线图在服务器端就画好；顾问拒答话术的「项目库」改成「学校库里该校的页面」（后端只改了这一句）。部署后线上只读检查都通过。决定和理由见 `note/decisions.md` 10-31「产品站收尾」。
- **任务进度（`TASKS.md`）：** P0、P1 做完（卡在 MortyYJT 的除外）；P2 #1 知识缺口（#67）、#3 人工核验入口（#69）已部署，#2 可观测性跳过（没有 Langfuse key）。**下一条：P2 #4「界面收尾」**（`ledger-redesign` 剩 4.4、5.12、7.1、7.2、7.3、7.5）。
- **已有能力**（细节在对应 OpenSpec change 和 `docs/measurements.md`）：邮箱验证码登录（生产没开）、顾问检索与评估（`api/evals/`）、限流与 token 额度（Redis，连不上就 503）、截止日期和学术要求入库、采集队列（Celery + Redis，worker/beat）、对话持久化（PG checkpointer）、混合检索（没有 `EMBED_API_KEY`，实际跑 `fts`）、快照 RAG、概括忠实度判官、同名学校合并、模型不可用降级、知识缺口队列、人工核验入口（只有管理员能用，生产匿名模式下没人能用）。离线工具：抽取 `python -m app.collect.extract`（没部署）。
- **评估：** 顾问报数组 30 条已在最终代码上跑过，**别再拿它调参**，重跑对比只照实记录；CI 的 `advisor-eval` 只跑调参组。**忠实度评估第二版（10-31，PR #83）**：490 个字段（旧随机 100 + 按字段分层 390），「推不出」147 条，标签 Claude 盲标、**不人工复核**（MortyYJT 决定）；DeepSeek 判官检出 103/147（70.1%）、误伤 27/343（7.9%）、精确率 103/130（79.2%），按总体加权 69.3% / 5.7% / 82.3%；截止日期只检出 22/50（判官放过标签里多出的入学季）。旧集和 10-30 结果原样保留，CI 两份都回放。细节 `docs/measurements.md`「Summary faithfulness evaluation, second set」。
- **未归档的 OpenSpec change：** hybrid-retrieval、snapshot-rag（各剩 1 项，都卡在 MortyYJT 的 `EMBED_API_KEY`）、ledger-redesign（P2 #4 进行中）。account-login、knowledge-gaps 已在 10-31 文档审计 PR 里归档（最后一项「部署」10-30 已做完）。
- **仓库整理（10-30）：** 不用 Claude Code 钩子（#71 删了 `guard.sh`）；删了学习用的 `note/interview/`（#72，git 历史里可找回）。`note/design/` 保留：代码注释和 README 把它当设计依据引用。钩子删了以后，「不推 main、不 force push、不碰密钥文件」只靠规则；GitHub 上 main 有分支保护（必须过 `backend`、`web`）。
- **文档（10-31 精简）：** `docs/` 全是英文：`deploy.md`（部署与运维）、`measurements.md`（各任务的测量、命令和注释，从 `TASKS.md` 挪来）、`product/PRD.md`、`images/`（README 截图）；`TASKS.md` 每条只留一行；`openspec/specs/` 15 份（#73 归档了 4 个已完成的变更，10-31 文档审计又归档 2 个）。`note/` 保持中文。
- **README（10-31，PR #82 已合并）：** 全英文，每个数字链到 `docs/measurements.md` 或 PRD；忠实度那条在 PR #83 换成第二版评估的数。决定见 `note/decisions.md` 10-31「README 重写」。
- **MortyYJT 10-31 的两个决定**（见 `note/decisions.md`）：① 不做「用户自带 API key」，项目自用；登录模式打开后把顾问限制为只有登录账号能用（还没做，排在登录模式之后）。② 登录模式不等腾讯云 SES，改用个人 QQ 邮箱或 Gmail 的 SMTP 授权码（见「卡在 MortyYJT」第 1 条）。
- **DeepSeek 余额（10-31）：** 19.00 元（本任务前 19.29；忠实度评估第二版花约 0.29 元，含一次中途停掉的启动和同期生产用量）。
- **待做（不卡在 MortyYJT）：** ① 忠实度回填：先查余额，再 `cd api && python -m app.collect.faithful --apply --budget-cny 5` 补判 125 个项目和中国学生要求 2,278 条（估约 3 元，见 `docs/measurements.md`「Summary faithfulness check」），提交改动的采集文件，按 `docs/deploy.md`「Import collected data」导入生产；余额不足期间因 402 记成 `deferred` 的采集页照旧到期（看数：`... exec -T db psql -U leapashore -d leapashore -c "select count(*) from collect_pages where last_error like 'model unavailable:%'"`）。② P2 #4 界面收尾。③ 另一个分支 `claude/retrieval-eval-v2` 由别的会话在做（不在本 PR）。
- **本机：** 库卷 `leapashore_pgdata`、Redis 卷 `leapashore_redis-data`（10-31 从旧卷复制并改名，旧卷已删），连接串 `leapashore:leapashore@localhost:55432/leapashore`。`make api-dev-bg` 默认登录模式，验证码写到 `api/var/mail.log`（不发信）；走查要求后端在登录模式，否则直接退出并说明。

## 卡在 MortyYJT（10-31）

1. **开登录模式（10-31 改用个人邮箱）**：MortyYJT 在 QQ 邮箱开 IMAP/SMTP 拿 16 位授权码（`smtp.qq.com:465` SSL），或在 Gmail 开两步验证后建应用专用密码（`smtp.gmail.com:465` SSL），然后**自己**在服务器 `deploy/.env` 填 `AUTH_ENABLED=true`、`MAIL_BACKEND=smtp`、`SMTP_HOST`、`SMTP_PORT=465`、`SMTP_USER`、`SMTP_PASSWORD`、`MAIL_FROM`（发件地址和 `SMTP_USER` 同一个；不要发在聊天里，也不进仓库）。步骤见 `docs/deploy.md`「Switch to sign-in mode」第 1–2 步；之后任何 agent 做第 3–8 步（检查变量、备份、重建 api、MortyYJT 登录收信、给 MortyYJT 管理员权限）。**切换前要把隐私政策 `/privacy` 里「腾讯云邮件推送（SES）」改成实际用的邮箱服务商并部署。** 之后再做「顾问只给登录账号用」。
2. **审核隐私政策** `/privacy`（AI 草稿）正文，补联系方式。
3. **GitHub 邮箱隐私**：Settings → Emails 勾选「Keep my email addresses private」，否则合并提交会带私人邮箱。
4. **硅基流动 key（P1 混合检索的向量部分）**：本机 shell、`api/.env`、服务器 `deploy/.env` 都没有硅基流动的 key（10-30 只查了变量名）。MortyYJT 在 cloud.siliconflow.cn 建一个 API key，填进服务器 `deploy/.env` 的 `EMBED_API_KEY=`（本机评估另外 `export EMBED_API_KEY=…`）。之后任何 agent 都能做`docs/deploy.md`「Turn on vector retrieval」的步骤，并补跑报数组的 `vector`、`hybrid` 两组。`BAAI/bge-m3` 在价格页标「免费」（10-30 查）。
5. **Langfuse Cloud key（P2 第二条「可观测性」，已跳过）**：没有 key，按清单跳过；需要 MortyYJT 提供 Langfuse Cloud key 后再做（public + secret key，填服务器 `deploy/.env`；之后任何 agent 都能接着做这一条）。
6. **成为管理员（P2 第三条「人工核验入口」）**：要先开登录模式（第 1 条），然后 MortyYJT 用自己的邮箱在网站上登录一次，再由任何 agent 在服务器上跑`docs/deploy.md`「Switch to sign-in mode」第 8 步。之前 `/admin` 对谁都是 404。
7. **复核 AI 自主决定**（`note/decisions.md` 里标「待 MortyYJT 复核」的各条），主要是：顾问限流默认额度和 Redis 挂了就 503；顾问门槛「只有 CRICOS 课程名不算证据」是否太严、简称表、评估集标签；抽取器多条学术路线只留第一条；README 数据条款措辞和 QS 转载授权；忠实度评估第二版的分层方式和标注规则（`api/evals/faithfulness_set_v2.json` 的 `labelling.rules`）；两个手填占位项目要不要删（见下）。

## 开放问题

- 路线图时间轴的「今天」用 UTC 日期（`web/components/roadmap/Timeline.tsx` 的 `toISOString`），北京时间 0–8 点会显示前一天（10-31 凌晨截图显示「今天 10月30日」）；截止日期是否已过却按北京日期算。首页示例取 UTC 是 #80 有意为之，用户自己的路线图要不要改成北京日期没定，没改。
- 两个手填的 `待核验` 占位项目（`api/app/seed.py`：`cricos-103000K` Monash 人工智能、`cricos-111671D` 悉尼计算机）仍算「有要求」：英语一栏是「需同时满足 Monash 英语要求」这类指引，均分 60/65 是早期手填、没过 `verify`。待 MortyYJT 决定是否删掉这些手填值（删要连 `test_seed.py` 一起改）。
- 学术要求和截止日期入库后（PR #48），机器核对项目里只剩 4 个界面上看不到任何要求：都只有不带分数的语言说明（Emory 数学、芝加哥 2 个、USC 1 个；芝加哥的雅思只有单项 7.0、没有总分，导入器 `english_text` 只写有总分的）。只有说明文字的语言要求和中国学生要求要不要显示、怎么措辞，还没定。

- 生产顾问用的是 `api.deepseek.com` 的 `deepseek-chat`（服务器 `deploy/.env`），不是任务清单原来写的硅基流动 DeepSeek-V4-Flash；隐私政策按生产实际写的 DeepSeek。10-30 跑意图评估时 DeepSeek 返回的模型名是 `deepseek-flash`（价格页已不列 `deepseek-chat`，旧名仍可调用）。本机评估用的是 shell 里的 `DEEPSEEK_API_KEY`：`CHAT_BASE_URL=https://api.deepseek.com CHAT_MODEL=deepseek-chat CHAT_API_KEY="$DEEPSEEK_API_KEY"`。
- **待 MortyYJT 复核（顾问限流）**：默认额度（主体 10 次/分钟、60 次/小时；IP 30 次/分钟、200 次/小时；每天每主体 20 万、每 IP 60 万、全站 200 万 token）；Redis 挂了顾问就 503 是否可接受。改数字只要改服务器 `deploy/.env`（变量名见 `deploy/.env.example`）再重建 api。
- **待 MortyYJT 复核（顾问检索）**：简称表是否地道；门槛「只有 CRICOS 课程名不算证据」是否太严（本机 31 所学校因此对要求问题全部拒答，如墨尔本、麦考瑞）；评估集标签是 AI 标的。

- NTU 8 个托福 1–6 新分制的值（PR #48 起）显示为「TOEFL iBT 4.5（新版 1–6 分制）」：导入器按 `scale: "iBT 1-6"` 加注，采集文件没改。
- 抽取器的已知局限：`verify` 只保证引文逐字在页上、数字在引文里，`text`/`label`/`recommended` 是否忠实没查；同温度 0 下截止日期的拒收数在跑与跑之间能差一倍（模型时而从页面别处推年份）。
- 采集数据里需要人工确认的点写在各校 json 的 `notes` 里（旧清单可在提交 `1a9fa30` 的 handoff 里查到）。
- 截止日期会过期（10-30 按北京时间 3,555 条里 289 条已过，102 个项目全部已过）：界面在渲染时按当天判断、标「已截止」，库里不存状态。最晚的一条是 2028-02-01，随着时间推移越来越多项目会变成「全部已截止」，要靠 P1「采集队列」定期重采。
- CC BY-SA 校徽的署名（PR #80 起）在全站页脚，名单从 `overseas-institutions.json` 的 `logo_license` 读；以后加 CC 校徽要填 `logo_license` 和 `logo_source`，否则不会被署名。
- **Crawl-delay**（10-30 起遵守）：82 个已缓存的 robots.txt 写了 5–120 秒，快照工具以前一律 2 秒；补采时 13 个站点被按 2 秒抓了（数据保留，见 decisions）。
- 还没采到项目的学校 37 所，多数被拒，规则不允许绕过。找列表页还能接着做：把新 URL 写进 `_schools.json` 的 `listing_urls`，`python -m app.collect.queue discover <key>...`，worker 跑完 `export`。
- 队列采的 1,366 个项目页没有要求通过核对（多数学校把入学要求写在另一页，队列只读项目页本身），在文件里是 `待人工`、不入库。
- 快照 RAG 的已知局限（10-30）：段落排序只看主题短语（学费/推荐信/面试），不看问题里的项目词（「MADS」），所以学费那句在同页另一块时可能排不进前 6（评估 t09、生产那一轮都是这样，回答只说「摘录里没有学费金额」）；核对只查逐字和数字，引文支不支持句子不查；4 道题的回答只是「摘录里没有该项目的页面」。南昆士兰大学 1 页当时没入库（两条同英文名的 CRICOS 学校行），PR #63 合并后已补。
- 混合检索评估的局限：调参组的相关集按学科大类标，`rules` 和 `fts` 都是 Recall@4 1.0 / Precision@4 0.98，分不出谁排得更好；要比较排序得补「点名具体项目」的标注题。
- 被拦的学校（按规则不绕过）：Monash、Melbourne、Macquarie、NUS 大部分、Oxford 主站、UCL（50 个后 403）、Bristol、Durham、Bath、Cardiff、York（16 个后 429）、QUB、Stanford 计算机系。

## 部署

部署步骤、导入、快照入库、换库、打开向量检索、切到登录模式和服务器上的坑都在 `docs/deploy.md`（英文）。各任务的测量和部署结果在 `docs/measurements.md`。

## 坑

- 「有要求」只有一个口径：后端 `has_requirement_data()`（`api/app/models/program.py`）、前端 `statesARequirement`（`web/lib/catalog.ts`）、顾问评估 `evals/run_advisor.py` 的相关集，改一处要三处一起改。
- 生产下次导入采集数据时，约 62 个多项目页面的最新版本引文会改写一次（PR #69 起一页多个项目的引文合并成一份），这是正常的。
- **DeepSeek 余额是生产和本机共用的**（不同 key、同一账户）。跑大批量付费任务前先查 `curl -s https://api.deepseek.com/user/balance -H "Authorization: Bearer $DEEPSEEK_API_KEY"`，预算要低于剩余余额，不只是低于任务上限（10-30 回填把余额用光，生产顾问跟着 402）。
- **`sources.verified_at` 有触发器护栏**（PR #69 起）：测试、脚本、手敲 SQL 都不能直接把它设成非空值（报 `sources.verified_at is written only by an admin's confirmation`，42501）；要一个核验过的页面就走 `app.services.source_verification.verify`（管理员账号）。设回 NULL 不受限。新代码要写这个字段，`tests/test_verified_at_writers.py` 会失败，先想清楚再进白名单。`pg_restore` 先灌数据后建触发器，恢复备份不受影响。
- 采集文件里的 `summary_check` 是判官判决；改了某一栏的声明模板（`faithful.statement`）就要 `python -m app.collect.faithful --forget <field>` 再回填，旧判决回答的是另一句话。队列 `export` 会把文件里内容相同的值的判决带到新结果上。
- 本机库（PR #58 起）是 `pgvector/pgvector:pg16`、卷 `leapashore_pgdata`（10-31 从旧卷复制过来并改名）、`C` 排序。`C` 排序下 `ORDER BY name` 是码位顺序（大写在小写前），和以前 Alpine 的行为一样，测试里按名字排序的断言依赖它。
- 顾问检索的排序由 `ADVISOR_RETRIEVAL` 决定；测试和评估可以显式传 `ranking=`。改 `subjects.json` 的 `gloss` 会改变全文检索的词（中文学科词经 gloss 变成英文词），不只是测试用。

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
- `make verify` 的走查（PR #80 起）在浏览器里拦下 `/api/advisor/*` 返回桩回复，不会真的问顾问、不花模型钱；要验证顾问本身走后端测试和 `api/evals/`。本机后端也没有 `CHAT_API_KEY`。
- 线上只读检查别打开 `/roadmap`、`/tiers`、`/portfolio`、`/me`：匿名模式下它们会读 `/api/profile`，建一个匿名主体（`/roadmap` 还会写 31 条任务）。**项目详情页 `/programs/<id>` 也会**读 `/api/profile` 和 `/api/applications`（`ProgramActions` 的 `useProfile`），10-31 截 README 图时才发现；要在线上截项目页，就在浏览器里把这些请求拦掉（README 截图就是这么做的）。10-31 部署后的检查打开过 `/roadmap`，那个主体已按 id 删除。
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
