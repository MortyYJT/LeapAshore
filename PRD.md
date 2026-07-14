# OfferPilot 留学申请规划 Agent — 一天版 PRD

版本：v0.2  
日期：2026-07-14  
产品形态：桌面优先的完整 Web 产品 Demo  
项目目标：作为大厂 Agent / 大模型应用实习的简历项目

## 1. 产品定义

OfferPilot 是一个面向澳洲计算机类硕士申请者的申请规划 Agent。

用户登录并填写学术背景后，系统检索具体项目，调用确定性工具检查 GPA、院校背景、专业相关性、先修课程和语言要求，再输出带官方来源的冲刺、匹配、稳妥和暂不推荐结果，并生成下一步申请行动清单。

它不是聊天机器人，也不是简单的学校列表。完整产品价值是：

1. 把零散背景整理成结构化申请档案。
2. 把学校官网要求转化为可执行的门槛检查。
3. 用 Agent 编排检索、工具调用、解释和引用校验。
4. 把推荐结论继续转化为申请任务，而不是停留在答案层面。

## 2. 一天版目标

一天内完成一个可公开演示、可运行测试、可在面试中讲清楚的产品闭环：

> 首页 → Demo 登录 → 填写/修改背景 → 运行 Agent → 查看项目推荐 → 查看项目证据 → 查看申请行动清单 → 查看历史运行记录

一天版完成标准：

- 前端核心流程完整，无死按钮。
- FastAPI 提供与前端流程对应的接口。
- 至少维护 6 个具体项目，不再只做学校级推荐。
- Agent 至少展示 5 个可解释步骤。
- 每条推荐绑定至少 1 个官方项目来源。
- 硬门槛由可测试的 Python 工具判断，不由 LLM 猜测。
- 有登录、资料、项目、推荐历史、行动计划的数据模型。
- 前后端均有基础测试和失败状态。
- GitHub 保持多次语义化提交，README 能让陌生人运行项目。
- 在线 Demo 可完整体验；若 Python API 未单独部署，前端使用同规则 Demo fallback，并明确标注。

## 3. 目标用户与核心场景

### 目标用户

- 准备申请 2027 年澳洲计算机、IT、AI、Data Science 硕士的中国本科生。
- 不清楚不同项目的背景、均分、先修课和语言要求。
- 希望先得到一份有依据的组合，再投入时间准备材料。

### 核心任务

用户需要回答三个问题：

1. 以我的背景，哪些具体项目值得申请？
2. 每个结论的依据是什么，还有哪些信息没有核验？
3. 我下一步应该补什么材料、在什么顺序下推进？

## 4. 产品范围

### 4.1 首页

- 明确展示“项目级推荐、Agent 工具调用、官方来源引用”。
- 主按钮进入 Demo 登录。
- 次按钮直接查看预设案例结果。
- 展示可验证指标：项目数、工具数、来源覆盖率。

### 4.2 Demo 登录

- 邮箱和密码表单。
- 后端返回 Demo Bearer Token 和用户信息。
- 错误、加载、成功状态完整。
- 页面必须说明：当前是 Demo Auth，不冒充生产级认证。

### 4.3 申请背景

必填字段：

- 本科院校
- 院校层级：985、211/双一流、双非、海外重点、其他
- 本科专业
- GPA 与满分制
- 目标方向
- 入学时间

选填字段：

- IELTS/TOEFL 成绩
- 实习、科研和项目经历

能力要求：

- 支持保存、读取和修改。
- 校验错误可理解。
- 提供完整的预设 Demo 数据，保证面试时可快速演示。

### 4.4 Agent 运行页

运行时展示以下步骤：

1. `normalize_gpa`：统一换算成绩。
2. `retrieve_programs`：检索目标方向的具体项目。
3. `check_hard_constraints`：检查成绩、背景、先修课和语言。
4. `rank_portfolio`：生成申请组合。
5. `validate_citations`：确认推荐结果绑定官方来源。

每一步展示 `queued / running / completed / failed` 状态。失败时提供重试和返回修改背景入口。

### 4.5 推荐报告

- 展示本次 Run ID、工作流版本和用户背景摘要。
- 展示工具成功率、引用覆盖率、满足基础门槛数量和缺失信息。
- 支持按冲刺、匹配、稳妥、暂不推荐筛选。
- 每张项目卡展示：
  - 学校与具体项目
  - 城市、学制
  - 推荐档位与匹配分
  - 基础门槛状态
  - 主要理由
  - 风险/待核验项
  - 官方来源链接
- 明确声明“匹配分不是录取概率”。

### 4.6 项目详情

- 展示具体项目名称、学校、城市、学制。
- 展示 GPA 检查结果、专业相关性、先修课和语言要求。
- 展示 Agent 使用的原始来源摘录、来源编号和核验日期。
- 支持打开官方项目页。
- 提供下一步核验清单。

### 4.7 行动计划

根据推荐结果生成 5 个左右任务：

- 核验成绩单课程
- 确认语言成绩与小分
- 确认最终申请组合
- 记录申请轮次和截止日期
- 准备简历、文书、推荐信和成绩单

任务包含优先级和状态。一天版可使用内存存储，刷新后丢失必须有明确提示。

### 4.8 历史记录

- 展示历史推荐 Run。
- 每条记录展示时间、目标方向、入学时间、工作流版本和推荐数量。
- 支持重新打开报告与行动计划。

## 5. Agent 设计

### 5.1 核心原则

- LLM 负责理解、规划、追问和自然语言解释。
- Python 工具负责 GPA、硬门槛、排序和引用完整性。
- LLM 不输出或修改“录取概率”。
- 每个事实性判断必须能回溯到工具结果或官方来源。
- 工具失败时必须显式暴露，不允许静默生成结论。

### 5.2 运行模式

需要支持两种模式：

1. `deterministic-demo`：无模型密钥时运行，保证在线 Demo 稳定。
2. `llm-assisted`：配置兼容 OpenAI 的模型后，由模型负责规划/解释，但硬门槛仍调用同一组工具。

不得在 README 中把 `deterministic-demo` 冒充为真实 LLM Agent。面试时应能解释两种模式为什么共用同一套工具和输出 Schema。

### 5.3 Agent 输入

- 结构化 ApplicantProfile
- 项目数据集
- 当前时间与目标 intake
- 可选模型配置

### 5.4 Agent 输出

- `run_id`
- `workflow_version`
- `summary`
- `missing_information[]`
- `tool_trace[]`
- `recommendations[]`
- `citations[]`
- `action_plan[]`

## 6. 首批项目数据

一天版仅覆盖计算机与数据方向的 6 个项目：

- UNSW — Master of Information Technology
- University of Sydney — Master of Computer Science
- Monash — Master of Artificial Intelligence
- Monash — Master of Computer Science
- UQ — Master of Data Science
- UWA — Master of Information Technology

每条数据必须包含：

- 项目 Slug
- 学校、城市、学制、方向
- 最低成绩基线
- 中国院校特殊规则（若官方页面明确提供）
- 是否要求相关背景
- 先修课程
- 英语要求
- 官方 URL
- 来源摘录
- 来源编号
- 最近核验日期

数据录入原则：只录入能从官方页面核验的信息；无法确定时标记“需人工核验”，不得补全猜测。

## 7. 后端接口

### 公共接口

- `GET /health`
- `POST /auth/login`
- `GET /programs`
- `GET /programs/{slug}`
- `POST /agent/recommendations`：无登录的可复现 Demo 运行

### 登录后接口

- `GET /me/profile`
- `PUT /me/profile`
- `POST /me/recommendation-runs`
- `GET /me/recommendation-runs`
- `GET /me/recommendation-runs/{run_id}`
- `GET /me/recommendation-runs/{run_id}/action-plan`

### 接口要求

- 全部使用 Pydantic Response Model。
- 错误使用明确的 HTTP 状态码和可读 detail。
- CORS 通过环境变量配置，不能在正式说明中假设只有 localhost。
- OpenAPI `/docs` 可直接演示完整流程。

## 8. 数据与存储策略

### 一天版

- 使用 Repository/Store 抽象。
- Demo Auth、Profile、Run History 和 Action Plan 可使用进程内存储。
- README 明确说明刷新或服务重启会清空数据。

### 后续生产化

- Supabase Auth
- PostgreSQL
- SQLAlchemy 2 + Alembic
- Row Level Security 或严格的 user_id 数据归属校验

一天版不得为了“看起来完整”伪装成已经使用真实数据库。

## 9. 非功能要求

- 桌面端 1280px 宽度下完整展示，移动端核心流程可用。
- 所有按钮可点击，外链使用安全属性。
- Agent 运行必须有 loading、失败和重试状态。
- 推荐结果必须有空状态。
- 不把 API Key 提交到仓库。
- 前端 build、lint、测试通过。
- 后端 pytest 通过。
- README 包含架构、运行方式、Agent 两种模式、限制和演示步骤。

## 10. 评测与测试

### 后端单元/接口测试

- 健康检查。
- 项目列表与详情。
- Demo 登录和未认证访问。
- Profile 保存和读取。
- 推荐 Run 创建和历史读取。
- 行动计划生成。
- 双非院校特殊门槛。
- 非相关专业先修风险。
- 缺失语言成绩。
- 所有推荐包含官方引用。

### Agent Eval

至少准备 10 个固定案例，输出：

- 硬门槛判断准确率
- 引用覆盖率
- 缺失信息识别准确率
- 工具成功率
- 平均运行时间

评测结果必须真实运行后写入 README，不允许填占位或虚构数字。

## 11. 一天版不做

- 500 所学校的大规模数据库
- 自动爬虫与网页变更监控
- PDF/OCR 成绩单解析
- 正式支付和咨询系统
- 生产级 Supabase 登录
- 多 Agent 互相对话
- 精确录取概率
- 文书自动生成

这些能力进入后续路线，不阻塞一天版交付。

## 12. 一天执行顺序

### 第 1 阶段：后端产品闭环（2 小时）

- 完成认证、Profile、Program、Recommendation Run、History、Action Plan 接口。
- 保留 Store 抽象和 Demo 内存实现。
- 补接口测试。

### 第 2 阶段：前端完整流程（2.5 小时）

- 登录、背景、Agent Run、结果、项目详情、行动计划和历史记录全部可达。
- 接入 FastAPI；API 不可用时提供清楚标记的 Demo fallback。
- 补 loading、error、empty、retry 状态。

### 第 3 阶段：LLM 模式与评测（1.5 小时）

- 增加模型 Provider Adapter 和 `llm-assisted` 模式。
- 硬门槛继续走确定性工具。
- 跑 10 个固定 Eval 案例并记录真实指标。

### 第 4 阶段：工程化与发布（2 小时）

- GitHub Actions。
- README 架构图、演示路径、限制说明和评测表。
- 完整 build、lint、前后端测试。
- 多次提交、推送并重新部署在线 Demo。

## 13. 简历叙事

项目完成后应能真实表述：

> 基于 Next.js、FastAPI 和可插拔模型 Provider 构建完整留学申请规划产品；设计 Agent 编排项目检索、硬门槛检查、组合排序和引用验证工具，支持无密钥确定性 Demo 与 LLM 辅助模式；实现用户资料、推荐历史、项目证据和行动计划闭环，并通过固定 Eval 数据集衡量门槛判断、引用覆盖和工具成功率。

所有简历数字以最终真实测试结果为准。
