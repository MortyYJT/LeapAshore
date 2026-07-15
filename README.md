# OfferPilot — 可验证的留学申请规划 Agent

OfferPilot 是一个覆盖澳洲八大本科、授课型硕士、研究型硕士和博士的留学申请规划 Web 产品。用户登录并填写背景后，系统先在官方课程目录中定位方向；只有完成课程级核验的项目才会进入确定性门槛检查和推荐分档，随后生成带官方来源的申请组合、项目分析与行动计划。

> 匹配分不是录取概率。最低门槛、名额和课程信息可能变化，最终以项目官网及学校正式审核为准。

## 在线体验

- Demo：https://offerpilot-study.jammy-mole-2081.chatgpt.site
- FastAPI 文档：本地启动后访问 http://localhost:8000/docs

## 产品流程

1. 注册账户、验证邮箱并建立可撤销的登录会话
2. 登录后填写或修改申请背景
3. 与 AI 申请顾问对话，直接修改偏好、重跑方案或创建待办
4. 粘贴成绩单文本，逐项目核验先修课程
5. 查看项目级冲刺、匹配、稳妥与暂不推荐结果
6. 推进带截止日期和提醒的申请任务
7. 回看历史方案与 Agent 执行审计
8. 提交 Beta 反馈，管理员在运营后台跟进用户、反馈和项目来源复核

## Agent 架构

```mermaid
flowchart LR
    UI[Next.js 产品界面] --> API[FastAPI]
    API --> ORCH[Agent Orchestrator]
    ORCH --> GPA[normalize_gpa]
    ORCH --> RET[retrieve_programs]
    ORCH --> RULES[check_hard_constraints]
    ORCH --> RANK[rank_portfolio]
    ORCH --> CITE[validate_citations]
    RET --> DATA[官方项目数据]
    RULES --> DATA
    CITE --> DATA
    ORCH <--> LLM[Ollama · Qwen2.5 0.5B]
    ORCH --> TASKS[任务与提醒工具]
    ORCH --> TRANSCRIPT[成绩单课程核验工具]
    API --> STORE[Store Adapter: Memory / SQLite / PostgreSQL]
```

核心设计原则：

- Agent 负责编排、补充信息判断和解释。
- 硬门槛由可测试的 Python 工具处理，LLM 不能修改档位、分数或引用。
- 每条推荐绑定官方项目页、来源编号、摘录和核验日期。
- 工具或模型不可用时显式降级，不静默伪造结论。

## 两种运行模式

### `deterministic-demo`

无模型密钥时自动启用。完整执行同一组确定性工具与引用校验，顾问仍能识别常见偏好变更和任务指令。

### `llm-assisted`

服务端通过 Ollama 自托管 Qwen2.5 0.5B，不需要任何模型 API Key。模型输出受 JSON Schema 约束，服务器只允许白名单工具和档案字段；硬门槛和排序仍由确定性工具完成。模型服务不可用时会安全降级。

```env
AGENT_MODE=llm-assisted
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:0.5b
```

## 课程覆盖与核验边界

当前产品范围为 8 所大学 × 4 个学位层次 × 12 个专业大类，共 384 个目录覆盖组合。专业大类包括计算机与数据、商科与金融、工程、教育与社会科学、生命科学、医学与健康、法律与犯罪学、自然科学与数学、人文与语言、建筑规划与设计、传媒艺术与音乐、环境与农业。

“目录覆盖”表示产品能把用户带到对应学校的官方课程入口，不表示已经掌握具体课程的录取要求。只有标记为“已核验”的具体项目才能参与冲刺、匹配、稳妥分档；其他组合返回官方目录与待核验提示，不生成推测性录取结论。

## 首批已核验项目数据

当前维护 6 个计算机与数据方向项目：

- UNSW — Master of Information Technology
- University of Sydney — Master of Computer Science
- Monash — Master of Artificial Intelligence
- Monash — Master of Computer Science
- UQ — Master of Data Science
- UWA — Master of Information Technology

每条数据均包含官方 URL、门槛摘录、先修要求、英语要求和核验日期。数据位于 `api/app/program_data.py`；前端保留同规则 fallback，用于 Python API 未部署时的公开演示。

## Eval 结果

固定 Eval 集包含相关/非相关专业、高中低 GPA、4 分制换算、双非特殊门槛、语言缺失和经历缺失等 10 个案例。

| 指标 | 结果 |
|---|---:|
| 固定案例数 | 10 |
| 硬门槛判断准确率 | 100% |
| 缺失信息识别准确率 | 100% |
| 官方引用覆盖率 | 100% |
| 核心工具成功率 | 100% |
| 本地平均确定性运行时间 | < 0.2 ms |

以上结果由 `api/evals/run_eval.py` 在 2026-07-14 实际运行得到；CI 会重新运行质量门槛。小型固定集只用于防止规则回归，不代表真实录取预测能力。

## 技术栈

- 前端：Next.js App Router、React 19、TypeScript、Tailwind CSS
- API：FastAPI、Pydantic v2
- Agent：Ollama + Qwen2.5 0.5B + Structured Outputs + 服务端白名单工具执行
- 测试：Node Test Runner、pytest、固定 Agent Eval
- 持久化：Repository 抽象、进程内 Demo Store、SQLite、PostgreSQL JSONB
- 安全：scrypt 密码哈希、HttpOnly/SameSite 会话 Cookie、哈希令牌、限流、安全响应头、服务端密钥、逐请求鉴权
- 账户：邮箱验证、密码重置、会话撤销、账户停用、数据导出与删除
- 可观测性：请求 ID、结构化访问日志、可选 Sentry、模型/Prompt/Workflow 版本、耗时、Token 与工具轨迹
- 工程化：GitHub Actions、Docker Compose、Caddy、Sites/Vercel 前端预览

## 本地运行

需要 Node.js 22.13+、pnpm 11 和 Python 3.12+。

```bash
pnpm install
pnpm dev
```

另开终端启动 API：

```bash
cd api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

复制环境变量示例：

```bash
cp .env.example .env.local
```

前端配置 `NEXT_PUBLIC_API_URL=http://localhost:8000` 后会连接 FastAPI。连接失败时界面会明确显示 `Demo fallback`，并继续使用同规则的浏览器会话演示。

如需在本机启用真实小模型，安装 Ollama 后执行：

```bash
ollama pull qwen2.5:0.5b
LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434 uvicorn app.main:app --reload
```

如需让 API 重启后继续保留资料和推荐历史，配置：

```env
DATABASE_PATH=./data/offerpilot.db
```

SQLite 适配器会自动建表，并通过 `user_id` 隔离 Profile 与 Agent Run。它适合本地 Demo、单机部署和面试演示；无状态云函数应改接托管 PostgreSQL。

生产环境配置 PostgreSQL 后会优先使用共享数据库：

```env
DATABASE_URL=postgresql://user:password@host:5432/offerpilot
```

PostgreSQL 适配器将 Profile、顾问会话、方案、任务和运行审计存入 JSONB，允许模型与工作流 Schema 继续演进。

## 无 Key 全栈部署

本地完整运行：

```bash
docker compose up -d --build
```

如果要按真实 SMTP 流程验收邮箱验证和密码重置，可启用仅绑定本机的 Mailpit 覆盖配置：

```bash
docker compose -f compose.yaml -f compose.mailpit.yaml up -d --build
```

邮件会由 API 通过 SMTP 投递，在 `http://localhost:8025` 查看。Mailpit 只用于本地验收，管理界面不暴露到局域网；生产环境仍使用 `compose.production.yaml` 中的真实 SMTP 配置。

启动后可以一键验证“注册 → 收到验证邮件 → 登录 → 收到重置邮件 → 旧密码失效”的完整链路：

```bash
api/.venv/bin/python api/evals/email_e2e.py
```

首次启动会自动拉取约 398MB 的 Qwen2.5 0.5B 模型。浏览器访问 `http://服务器地址:8080`。完整拓扑为：

- Caddy：唯一公开入口，同域转发 Web 与 `/api`
- Next.js：产品界面
- FastAPI：认证、Agent 编排、专业工具与审计
- Ollama：仅在 Docker 内网提供模型推理，不暴露端口
- PostgreSQL：持久化账户、档案、会话、任务与审计

生产环境至少应设置独立数据库密码：

```bash
POSTGRES_PASSWORD='replace-with-a-strong-password' docker compose up -d --build
```

这里的数据库密码是服务器基础设施配置，不需要任何普通用户填写，也不是模型 API Key。

正式封闭 Beta 使用生产覆盖配置：

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production -f compose.yaml -f compose.production.yaml up -d --build
```

生产模式强制要求 PostgreSQL、SMTP、HTTPS 域名、安全 CORS 和管理员邮箱；缺失时 API 拒绝启动。Caddy 自动管理 HTTPS，Alembic 在 API 启动前执行迁移，备份容器每天生成 PostgreSQL 备份并保留 7 天。完整步骤见 [Beta 上线 Runbook](./docs/BETA_LAUNCH_RUNBOOK.md)，安全基线见 [SECURITY.md](./SECURITY.md)。

## Vercel 前端预览

仓库根目录仍保留 `vercel.json`，用于 Web 与普通 FastAPI 的在线预览：

- `/` → Next.js Web service
- `/api/*` → FastAPI service（服务入口保留并挂载 `/api` 前缀）

Vercel Serverless 不适合常驻加载 Ollama 模型，因此无 Key 的完整 Agent 版本应使用上面的 Docker Compose 部署；现有 Sites 链接继续作为无需后端的稳定产品预览。

## API

公共接口：

- `GET /health`
- `GET /health/readiness`
- `GET /llm/status`
- `POST /auth/login`
- `POST /auth/register`
- `POST /auth/verify-email`
- `POST /auth/resend-verification`
- `POST /auth/forgot-password`
- `POST /auth/reset-password`
- `POST /auth/logout`
- `GET /catalog/facets`
- `GET /catalog/coverage`
- `GET /programs`
- `GET /programs/{slug}`
- `POST /agent/recommendations`

登录后接口：

- `GET|DELETE /me`
- `GET /me/export`
- `GET /me/profile`
- `PUT /me/profile`
- `POST /me/recommendation-runs`
- `GET /me/recommendation-runs`
- `GET /me/recommendation-runs/{run_id}`
- `GET /me/recommendation-runs/{run_id}/action-plan`
- `POST /me/advisor/threads`
- `POST /me/advisor/threads/{thread_id}/messages`
- `GET /me/advisor/audits`
- `POST /me/transcript/analyze`
- `GET|POST /me/tasks`
- `PUT /me/tasks/{task_id}`
- `GET|POST /me/feedback`

管理员接口：

- `GET /admin/stats`
- `GET|PUT /admin/users`
- `GET|PUT /admin/feedback`
- `GET /admin/program-sources`

## 验证

```bash
pnpm run lint
pnpm test
pnpm audit --prod

cd api
.venv/bin/pytest -q
.venv/bin/pip-audit --local
PYTHONPATH=. .venv/bin/python evals/run_eval.py
```

## 当前边界

- 未配置 `DATABASE_PATH` 时，Profile、历史记录和行动计划使用进程内 Store；API 重启会清空。
- 生产部署应配置 `DATABASE_URL`；SQLite 不适合作为无状态云函数的共享数据库。
- 在线站点在 FastAPI 未单独部署时使用浏览器会话 fallback，刷新会清空。
- 当前成绩单工具处理可复制文本；扫描版 PDF/OCR 仍需接入文件存储和视觉模型。
- 来源模块会标记超过 30 天未核验的数据，但不会在无人审核时自动覆盖申请门槛。
- 系统不生成“录取概率”，也不会把模型推断伪装成学校官方结论。
- 当前内存限流适用于单 API 实例封闭 Beta；多副本部署前需要迁移到 Redis。
- SMTP 服务商、域名 SPF/DKIM/DMARC、服务器防火墙与异地备份需要在真实域名上线时完成最终配置。

## Beta 上线门槛

- 自动化：前端构建、lint、产品流程测试、API 测试和 Agent Eval 全部通过。
- 流程：登录 → 背景 → 目标学位/方向 → Agent → 结果/诚实空状态 → 行动计划可完整走通。
- 数据：384 个目录组合均有官方入口；推荐结果必须来自已核验具体项目并带来源。
- 熟人测试：至少 5 名不同背景用户完成主流程，任务成功率不低于 80%，阻断性问题为 0。
- 上线：修复所有阻断问题，并记录高频困惑、无结果搜索和用户最想要的项目，作为下一轮课程核验优先级。

完整一天版产品规格见 [PRD.md](./PRD.md)。

## License

MIT
