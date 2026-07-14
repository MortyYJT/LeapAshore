# Codex 执行交接

请先完整阅读 `PRD.md`，然后直接实现，不再进行产品方向讨论。

## 当前仓库状态

- `main` 相对远端已有 1 个本地提交：`feat: add auditable program recommendation agent`。
- 已提交内容包括：6 个项目数据、Agent 输出 Schema、5 步工具链、项目级推荐接口和基础测试。
- 工作区存在未提交的开发中改动：
  - Demo Auth、Profile、Run History、Action Plan 后端接口与 Store 抽象。
  - 前端从学校级推荐升级为项目级 Agent 流程。
  - Agent Run、证据概览和引用样式。
- 不要重置或丢弃这些改动；先运行检查，修复后继续完成。

## 最新检查结果

- 后端：`5 passed`，仅有现有 Starlette/httpx 弃用警告。
- 前端 build：通过。
- 前端 lint：1 个错误，`app/page.tsx` 的 Agent 动画 effect 内同步调用了 `setCompletedSteps(0)`；应在启动 Agent 的事件处理函数中重置，effect 只负责订阅计时器。
- 前端测试：2 个旧断言失败，测试仍在检查旧首页文案和 8 个学校级 slug；应改为检查新首页文案、6 个项目级 slug、5 个工具名、来源引用和免责声明。
- 当前尚未完成：前端真实 API 接入、行动计划页、历史记录页、LLM Provider、Eval、CI、README 更新和部署。

## 执行优先级

1. 保证仓库当前未提交代码能通过后端测试、前端 build 和 lint。
2. 完成完整产品路径：登录 → Profile → Agent → Report → Program → Action Plan → History。
3. 前端优先真实调用 FastAPI；保留显式标注的 Demo fallback。
4. 增加 LLM Provider Adapter，但不要让 LLM 决定硬门槛。
5. 增加至少 10 个固定 Eval 案例并跑出真实结果。
6. 更新 README 和 `.env.example`。
7. 添加 GitHub Actions。
8. 按逻辑拆分多次 commit，推送 GitHub，重新部署 Demo。

## 必须通过的验收

- `pnpm run build`
- `pnpm run lint`
- `pnpm test`
- `cd api && .venv/bin/pytest -q`
- Git 工作区最终干净。
- GitHub 上可看到多次语义化提交。
- 在线 Demo 可以从首页完成主流程。
- README 不夸大 Demo Auth、内存存储或 deterministic 模式。

## 建议提交拆分

1. `feat: complete authenticated planning workflow`
2. `feat: connect agent product experience`
3. `test: add agent evaluation suite`
4. `ci: validate frontend and api`
5. `docs: document architecture and demo limits`

## 禁止事项

- 不删除或压缩为一次提交。
- 不把匹配分描述成录取概率。
- 不虚构评测数字。
- 不提交密钥。
- 不为了展示而引入没有实际用途的多 Agent。
