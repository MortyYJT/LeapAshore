# Session handoff

**唯一的当前状态文件。会话结束时覆盖，开始时读，并先对照 `git status` 和 `git log`。**

## 现在在哪（2026-10-29 深夜，MortyYJT 在睡觉，Claude 自动推进）

- 分支 `claude/ledger-redesign`（从 main 拉出，未合并）。线上 http://43.161.224.82 仍是改名前的版本。
- 今晚做三件事（MortyYJT 原话：「补数据，爬取 qs 前 200 的……还有补一下缺失校徽，然后去写代码，就那些不太可能会变动的后端部分」）：
  1. **录取要求采集**：QS 2027 前 200 中除中国大陆外的 190 所，按 `api/data/requirements/_schools.json` 的 wave 顺序（澳 → 港 → 新 → 英 → 美 → 其余），由子代理逐校采集，额度用完为止。
  2. **补校徽**：`scripts/fill-logos.py`（官网图标 → Wikidata P154/P8972/P158 → Commons 自由许可文件）。
  3. **稳定的后端**：已完成，见下。
- 界面原型（个人网站配色 + 渐变 + 动画）在 `.taste-skill/prototype/`（被 git 忽略，只在本机），MortyYJT 已认可「总体没问题」。

## 已完成并提交（按提交顺序）

- `docs(openspec)`：OpenSpec change `ledger-redesign`（前端合并 + 视觉），PRD 档位改「稳妥」、§7.7 第 5 条界面用词对照表
- `feat(collect)`：`app.collect.snapshot`（robots.txt、同域 2 秒间隔、403/429 记录不绕过、`--render` 用本机 Chrome）、`app.collect.verify`（引文逐字核对 + 数字必须在引文里 + 截止日期的年月日都要在引文里；`--drop-failing` 删掉不过的值）、`app.collect.importer`（只写核对通过的字段，`verified_at` 永不写）
- `feat(catalog)`：`app.seed_catalog` 导入 2920 个 CRICOS 项目（id `cricos-<code>`），6 个占位项目并入 CRICOS 行（Monash CS 无对应，删除），删掉 6 项目镜像校验；`make seed` 已接上
- `feat(applications)`：申请状态加 submitted / offered / rejected；服务层也校验
- `feat(programs)`：`/api/programs` 支持 ids / field / provider / has_requirements / limit≤100 / offset，`X-Total-Count`，有要求的排前面
- 数据：见下表

## 采集进度（每校一个 json，在 `api/data/requirements/`；表由脚本从文件生成）

共 32 所、1764 个项目、1758 个机器核对。各校的特殊情况写在各自 json 的 `notes` 和提交说明里。

| school_key | 项目 | 机器核对 | 状态 |
| --- | --- | --- | --- |
| adelaide-university | 60 | 60 | partial |
| australian-national-university | 53 | 53 | partial |
| chinese-university-of-hong-kong | 61 | 61 | partial |
| city-university-of-hong-kong | 66 | 66 | complete |
| curtin-university | 50 | 50 | partial |
| hong-kong-polytechnic-university | 113 | 113 | complete |
| hong-kong-university-of-science-and-technology | 54 | 54 | complete |
| imperial-college-london | 165 | 165 | complete |
| london-school-of-economics-and-political-science | 64 | 64 | partial |
| macquarie-university | 0 | 0 | blocked |
| monash-university | 1 | 0 | blocked |
| nanyang-technological-university-singapore | 65 | 64 | partial |
| national-university-of-singapore | 6 | 6 | blocked |
| rmit-university | 79 | 79 | complete |
| ucl | 50 | 50 | blocked |
| university-of-bristol | 1 | 1 | blocked |
| university-of-cambridge | 59 | 59 | partial |
| university-of-edinburgh | 62 | 62 | partial |
| university-of-glasgow | 60 | 60 | partial |
| university-of-hong-kong | 66 | 66 | partial |
| university-of-leeds | 78 | 78 | partial |
| university-of-manchester | 61 | 61 | partial |
| university-of-melbourne | 0 | 0 | blocked |
| university-of-new-south-wales | 54 | 54 | partial |
| university-of-oxford | 9 | 6 | blocked |
| university-of-queensland | 60 | 60 | partial |
| university-of-sheffield | 67 | 67 | partial |
| university-of-sydney | 60 | 60 | partial |
| university-of-technology-sydney | 55 | 55 | partial |
| university-of-warwick | 64 | 64 | blocked |
| university-of-western-australia | 64 | 64 | partial |
| university-of-wollongong | 57 | 56 | partial |

被拦截（按规则不绕过）：Monash、Melbourne、Macquarie、NUS 大部分、Oxford 主站、UCL（50 个后 403）、Bristol（5 个请求后 403）。
需人工确认：UNSW 英语分数的学院对应、悉尼「Not available to student visa holders」、剑桥 "High II.i"↔"High 2:1"、帝国理工 46 个 MRes 是否算授课型、RMIT 7 条按名称匹配 CRICOS。
进行中：KCL、Birmingham、Durham、Nottingham、QMUL、Southampton；英国还剩 St Andrews 起 10 所，然后美国 38 所、其余地区。

## 校徽

- `scripts/fill-logos.py` 补了 16 个（5 个官网图标、11 个 Commons 校徽/印章），还剩 43 所用首字圆标
- Commons 的 CC BY / CC BY-SA 文件**需要在界面上署名**（`logo_license`、`logo_source` 已记在 fixture 行上），学校库页面还没有署名区

## 怎么继续采集

- 子代理简报：`api/data/requirements/README.md`（规则、格式、怎么省上下文）
- 起一个学校：让子代理读简报，给它 `school_key`；跑完后在主会话里 `cd api && .venv/bin/python -m app.collect.verify ../api/data/requirements/<key>.json` 复核再提交
- 入库：`cd api && .venv/bin/python -m app.collect.importer`（先 `make seed`）
- 快照在 `api/var/snapshots/`（不进库）；生产库没有快照，导入只依赖 json 里已写好的 `check`

## 已知问题 / 要 MortyYJT 决定

- 占位种子给 UNSW、悉尼的「均分门槛 65」其实是澳洲学位的 credit average，不是对中国学位的要求；导入采集数据后这两行会被覆盖为空（更诚实）
- 学术要求原文、截止日期目前只存在 json 和 `source_versions.body_text` 里，`programs` 表没有列；要展示就得加列（schema 变更，要先问）
- shell 里 `NODE_ENV=development` 会让 `next build` 失败，跑构建前 `unset NODE_ENV NODE_DEBUG`
- Playwright 自带 Chromium 截中文会截掉半个字，截图要用 `channel: 'chrome'`

## 验证状态

- 后端：266 条通过；前端 205 条通过（`make test` 全过）
- `make verify`：构建和测试通过；走查在「为你筛出的申请组合」一步失败，这是 PR #26 已记录的旧问题（新入口流程后走查需重写），不是今晚的改动造成的
- 本机 Turbopack dev server 报 "Next.js package not found" 后会无限刷新，走查改用生产构建（`BASE_URL=http://localhost:3100`）
- 一个全新上下文的审查子代理审过后端改动，1 个阻断 + 6 个应修问题已全部修复
- CI：没跑；部署：没动

## 怎么跑与部署

- 本地：`make dev` / `make test` / `make verify`
- 部署（仓库根目录）：rsync 到 `ubuntu@43.161.224.82:~/offerpilot/`（排除 node_modules、.next、.venv、
  .git、.env、deploy/.env、api/var、docs/screenshots），然后在服务器上
  `cd ~/offerpilot/deploy && sudo docker compose -f compose.prod.yaml up -d --build`
- 服务器密钥在服务器的 `~/offerpilot/deploy/.env`，不进库
- 这个分支上线前要在生产库跑一次 `make seed`（会导入 CRICOS 并迁移旧 slug）和 importer

## 坑

- 流式响应要自己写 cookie：返回 `StreamingResponse` 时必须调 `set_client_cookie`
- LangGraph `interrupt` 前不能有写操作：恢复时整个节点从头重跑
- 新访客可能还没有 `clients` 行：写组合前先 `load_or_create_profile`
- 对话存在 `InMemorySaver`，API 重启即丢；换 Postgres checkpointer 是 schema 变更，要先问
- 仓库本地 git 身份必须是 `MortyYJT` + noreply 邮箱（曾被设成 `rehearsal`）
- 公开仓库历史已于 10-28 改写去掉真名；已合并 PR 页面仍引用旧提交
