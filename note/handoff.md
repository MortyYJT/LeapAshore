# Session handoff

**唯一的当前状态文件。会话结束时覆盖，开始时读，并先对照 `git status` 和 `git log`。**

## 现在在哪（2026-10-30 凌晨，夜间采集因额度用完停止）

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

共 141 所、5337 个项目、5253 个机器核对。各校的特殊情况写在各自 json 的 `notes` 和提交说明里。

| school_key | 项目 | 机器核对 | 状态 |
| --- | --- | --- | --- |
| adelaide-university | 60 | 60 | partial |
| arizona-state-university | 69 | 69 | partial |
| australian-national-university | 53 | 53 | partial |
| boston-university | 40 | 40 | partial |
| brown-university | 38 | 37 | complete |
| california-institute-of-technology | 3 | 3 | complete |
| cardiff-university | 0 | 0 | blocked |
| carnegie-mellon-university | 41 | 41 | partial |
| chinese-university-of-hong-kong | 61 | 61 | partial |
| city-university-of-hong-kong | 66 | 66 | complete |
| columbia-university | 65 | 65 | partial |
| cornell-university | 24 | 24 | partial |
| curtin-university | 50 | 50 | partial |
| delft-university-of-technology | 0 | 0 | blocked |
| duke-university | 42 | 42 | partial |
| durham-university | 0 | 0 | blocked |
| emory-university | 24 | 24 | partial |
| epfl-ecole-polytechnique-federale-de-lausanne | 29 | 29 | complete |
| eth-zurich | 45 | 45 | complete |
| freie-universitaet-berlin | 30 | 30 | partial |
| georgia-institute-of-technology | 60 | 60 | partial |
| hanyang-university | 6 | 6 | blocked |
| harvard-university | 52 | 52 | complete |
| hokkaido-university | 9 | 9 | blocked |
| hong-kong-polytechnic-university | 113 | 113 | complete |
| hong-kong-university-of-science-and-technology | 54 | 54 | complete |
| imperial-college-london | 165 | 165 | complete |
| institut-polytechnique-de-paris | 41 | 41 | partial |
| institute-of-science-tokyo | 18 | 16 | partial |
| johns-hopkins-university | 52 | 24 | partial |
| kaist | 2 | 2 | blocked |
| king-s-college-london | 61 | 61 | partial |
| kit-karlsruhe-institute-of-technology | 13 | 13 | complete |
| korea-university | 45 | 45 | partial |
| kth-royal-institute-of-technology | 51 | 51 | complete |
| ku-leuven | 0 | 0 | blocked |
| kyoto-university | 15 | 8 | partial |
| kyushu-university | 18 | 6 | partial |
| lancaster-university | 62 | 62 | complete |
| london-school-of-economics-and-political-science | 64 | 64 | partial |
| ludwig-maximilians-universitat-munchen | 26 | 26 | partial |
| lund-university | 57 | 57 | partial |
| macquarie-university | 0 | 0 | blocked |
| massachusetts-institute-of-technology | 42 | 42 | complete |
| mcgill-university | 0 | 0 | blocked |
| mcmaster-university | 14 | 14 | partial |
| michigan-state-university | 13 | 11 | partial |
| monash-university | 1 | 0 | blocked |
| nagoya-university | 17 | 17 | complete |
| nanyang-technological-university-singapore | 65 | 64 | partial |
| national-university-of-singapore | 6 | 6 | blocked |
| new-york-university | 29 | 29 | partial |
| newcastle-university | 62 | 62 | partial |
| northwestern-university | 34 | 34 | partial |
| pennsylvania-state-university | 39 | 38 | partial |
| pohang-university-of-science-and-technology | 4 | 2 | blocked |
| politecnico-di-milano | 44 | 44 | complete |
| princeton-university | 9 | 9 | complete |
| purdue-university | 26 | 26 | partial |
| queen-mary-university-of-london | 139 | 137 | partial |
| queen-s-university-at-kingston | 11 | 11 | partial |
| queen-s-university-belfast | 0 | 0 | blocked |
| rice-university | 24 | 19 | complete |
| rmit-university | 79 | 79 | complete |
| sapienza-university-of-rome | 16 | 16 | partial |
| seoul-national-university | 4 | 2 | blocked |
| sorbonne-university | 19 | 19 | partial |
| stanford-university | 19 | 19 | partial |
| sungkyunkwan-university | 4 | 4 | blocked |
| technical-university-of-denmark | 27 | 27 | partial |
| technical-university-of-munich | 82 | 82 | complete |
| texas-a-m-university | 26 | 19 | partial |
| tohoku-university | 11 | 11 | partial |
| trinity-college-dublin-the-university-of-dublin | 55 | 55 | partial |
| ucl | 50 | 50 | partial |
| universitat-heidelberg | 11 | 10 | partial |
| universite-de-montreal | 37 | 37 | partial |
| universite-paris-saclay | 1 | 1 | blocked |
| universite-psl | 36 | 36 | partial |
| universiti-kebangsaan-malaysia | 0 | 0 | blocked |
| universiti-malaya | 61 | 61 | partial |
| universiti-putra-malaysia | 35 | 33 | partial |
| universiti-sains-malaysia | 54 | 54 | partial |
| universiti-teknologi-malaysia | 79 | 79 | complete |
| university-college-dublin | 0 | 0 | blocked |
| university-of-alberta | 0 | 0 | blocked |
| university-of-amsterdam | 32 | 32 | partial |
| university-of-auckland | 28 | 28 | partial |
| university-of-bath | 0 | 0 | blocked |
| university-of-birmingham | 60 | 60 | partial |
| university-of-bristol | 1 | 1 | blocked |
| university-of-british-columbia | 51 | 51 | partial |
| university-of-california-berkeley | 55 | 55 | partial |
| university-of-california-davis | 5 | 5 | blocked |
| university-of-california-los-angeles | 46 | 46 | partial |
| university-of-california-san-diego | 20 | 20 | complete |
| university-of-california-santa-barbara | 14 | 14 | complete |
| university-of-cambridge | 59 | 59 | partial |
| university-of-chicago | 19 | 19 | complete |
| university-of-copenhagen | 48 | 48 | complete |
| university-of-edinburgh | 62 | 62 | partial |
| university-of-exeter | 143 | 142 | complete |
| university-of-glasgow | 60 | 60 | partial |
| university-of-hong-kong | 66 | 66 | partial |
| university-of-illinois-urbana-champaign | 13 | 13 | partial |
| university-of-leeds | 78 | 78 | partial |
| university-of-liverpool | 67 | 67 | partial |
| university-of-manchester | 61 | 61 | partial |
| university-of-melbourne | 0 | 0 | blocked |
| university-of-michigan-ann-arbor | 24 | 24 | partial |
| university-of-new-south-wales | 54 | 54 | partial |
| university-of-north-carolina-at-chapel-hill | 23 | 23 | partial |
| university-of-nottingham | 64 | 64 | partial |
| university-of-osaka | 11 | 9 | partial |
| university-of-otago | 0 | 0 | blocked |
| university-of-oxford | 9 | 6 | blocked |
| university-of-pennsylvania | 65 | 65 | partial |
| university-of-queensland | 60 | 60 | partial |
| university-of-reading | 63 | 63 | partial |
| university-of-sheffield | 67 | 67 | partial |
| university-of-southampton | 77 | 77 | partial |
| university-of-southern-california | 70 | 70 | partial |
| university-of-st-andrews | 51 | 51 | partial |
| university-of-sydney | 60 | 60 | partial |
| university-of-technology-sydney | 55 | 55 | partial |
| university-of-texas-at-austin | 18 | 18 | partial |
| university-of-tokyo | 15 | 14 | partial |
| university-of-toronto | 24 | 24 | partial |
| university-of-warwick | 64 | 64 | partial |
| university-of-washington | 15 | 15 | partial |
| university-of-waterloo | 49 | 49 | complete |
| university-of-western-australia | 64 | 64 | partial |
| university-of-wisconsin-madison | 37 | 37 | partial |
| university-of-wollongong | 57 | 56 | partial |
| university-of-york | 15 | 15 | partial |
| university-of-zurich | 12 | 12 | partial |
| uppsala-university | 108 | 108 | complete |
| washington-university-in-st-louis | 11 | 11 | partial |
| western-university | 47 | 47 | complete |
| yale-university | 44 | 44 | complete |
| yonsei-university | 7 | 7 | blocked |

被拦截（按规则不绕过）：Monash、Melbourne、Macquarie、NUS 大部分、Oxford 主站、UCL（50 个后 403）、Bristol、Durham、Bath、Cardiff、York（16 个后 429）、QUB（robots.txt 403）、Stanford 计算机系（robots.txt 禁止）。
需人工确认：UNSW 英语分数的学院对应、悉尼「Not available to student visa holders」、剑桥 "High II.i"↔"High 2:1"、帝国理工 46 个 MRes 是否算授课型、RMIT 7 条按名称匹配 CRICOS、St Andrews 英语分数取自页面 data 属性、Exeter 中国要求表标注的是 2026 入学、Stanford 等校 TOEFL 同时给 0-120 和新 1-6 分制（界面怎么显示要定）。
需人工确认（10-30 白天新增）：
- JHU Carey：英语分数和学位要求取自 Carey 目录的学院政策页，项目页本身没链接过去（简报要求项目页指名）；“preferred minimum” 已标为建议分
- Yale MMS Global Business and Society：页面说 2027 届申请 2025 年 9 月开放，表格却是 2026-27 日期；采用了表格
- Yale MAM / GBS：截止日期按表格列位置标轮次，不是原文写的标签
- Stanford MS&E：“minimum expected score” 按最低分处理
- Harvard HSPH：45/65 学分两个版本同一网址（id 冲突已修）
- CMU MHCI：官网写 IELTS 总分 8.5，按原文收录，疑似学校笔误
- UIUC：英语分数取研究生院 limited-status（有条件录取）最低分，full-status 分数写在 prerequisites
采集暂停（10-30 傍晚子代理额度用完，墨尔本 18:40 重置）：190 所里 141 所有文件（13 所 0 项目=被拦或连不上），49 所未开始（欧洲约 28、其他 21，含中断的 Utrecht/Helsinki/RWTH/Aalto/Bologna/Leiden，均无文件）。收尾脚本 `finish.py` 在会话草稿区（复核→生成提交说明→提交推送→刷新本表）。
- Alberta 子代理用 curl（非诚实 UA）读过一次 www.ualberta.ca/robots.txt，返回 403，未引用
- Emory Economics and AI：页面说待董事会批准，2027 秋首届
- TAMU Statistics：截止日期标题写 Fall 2026，日期却是 2027-01-31，按原文收录
- Waterloo：MMath（CS、统计、精算等）学校标为 Master's, Research，但有 research-paper 选项，已收录——是否算授课型待定
- Queen's：MSc Computing、MSc 数学统计、MEd 有论文和项目两条路径，已收录——同 Waterloo MMath 一并定
- 【要 MortyYJT 决定】PDF：日本等校的招生要项只有 PDF，快照工具读不了；要读需加依赖（如 pypdf），本机也没有 pdftotext。未加。
- 首尔大学：TOEFL 80 / IELTS 6.0 / TOPIK 3 取自 2021 年更新的招生 FAQ（同时覆盖本科），可能过时
- 【前端待办】截止日期会随时间过去：现有 139 个早于 2026-10-29（多为下一届的第一轮或刚关闭的窗口）。界面需按当天日期标“已截止”，不能当成未来日期排时间线
- USM：所有主机 robots.txt 网络层读不到（URLError），不是明说禁止；换网络环境可重试
- USM 根因：服务器证书链不完整，Python 校验失败（浏览器能补中间证书）；UKM：robots.txt 超时。都没绕过（不关证书校验）
- UTM：28 个项目自己页面没写要求，套用了全校授课型/混合型的统一 CPA 和英语线（招生办列表把它们归入该类）——严格读法下应删
- PSL：psl.eu 的 robots.txt 报 TLS 自签名证书链错误，主站未采；用了 Dauphine-PSL 和 ENS-PSL 子站
- KU Leuven：主站 robots 403；课程指南 onderwijsaanbod 先能访问后全部超时，可稍后按 /opleidingen/e/SC_<id>/toelatingsvoorwaarden 重试
- 【更正】前面记的 USM “服务器证书链不完整”和 PSL “自签名证书”判断有误：真正原因是本机 macOS 证书库缺 HARICA 2021 根证书，已修（用 certifi，未关校验）；USM 正在重跑，PSL 主站和索邦物理子站可补跑。【要 MortyYJT 知悉】快照工具会在已安装时使用 certifi（httpx/requests 间接带入，未加依赖声明）

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

- 后端：287 条通过（白天新增：项目变体 id、建议分、美国/加拿大日期顺序、www 别名封禁、多语种月份、Nov.6 写法、robots.txt 无应答的原因与重试）；前端 205 条通过
- 快照工具原先只对请求的 URL 查 robots.txt、不查重定向落点（Caltech 子代理发现），已修；4 个不该存的本地快照已删，没有数据引用它们
- 种子测试原先依赖开发库只有种子数据，导入采集数据后 5 条失败；已改成不依赖。注意：跑 `test_seed.py` 会把 5 个占位项目重置成种子版本，要看导入效果就重跑 importer
- `make verify`（10-30 傍晚重跑）：后端 290、前端 205 通过；走查在 :3000 dev server 超时、在 :3100 生产构建卡在「为你筛出的申请组合」——仍是旧问题。导入器本机跑通且幂等，`--prune` 清掉 306 行旧 id 残留，0 个来源带 verified_at。CI：最新推送 8e7917f 通过。
- 旧记录：构建和测试通过；走查在「为你筛出的申请组合」一步失败，这是 PR #26 已记录的旧问题（新入口流程后走查需重写），不是今晚的改动造成的
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
