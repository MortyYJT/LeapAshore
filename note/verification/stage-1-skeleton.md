# 第一阶段骨架验收证据

日期：2026-10-05（Australia/Melbourne）
范围：`web/` 前端骨架（T1–T3）
验证人：主助手（实机执行）

状态分开陈述，未验证的项一律标未验证。

---

## 1. 构建

命令：`make build`（即 `cd web && npm run build`）

结果：**通过**

```
▲ Next.js 16.2.11 (Turbopack)
✓ Compiled successfully in 1178ms
  Running TypeScript ...
  Finished TypeScript in 778ms
✓ Generating static pages (3/3) in 122ms

Route (app)
┌ ○ /
└ ○ /_not-found
```

TypeScript 严格模式开启（`strict: true`），无类型错误。

## 2. 端到端走查

命令：`make screenshots`（即 `node scripts/e2e-walkthrough.cjs`）

驱动真实 Chromium（借旧项目的 `@playwright/test`，本项目不额外安装），依次执行：
填完 10 步引导 → 生成方案 → 选校组合 → 确认组合 → 主界面 → 点节点 → 勾材料 → 切四个分栏 → 刷新。

结果：**16 张截图全部产出**

```
docs/screenshots/01-step1-education.png
docs/screenshots/03-step3-school-detected.png
docs/screenshots/08-portfolio.png
docs/screenshots/10-flow.png
docs/screenshots/13-home.png
docs/screenshots/15-advisor.png
...（共 16 张）
```

## 3. 运行期错误

浏览器 `console` 的 error 级消息 + `pageerror`：

```
=== JS 错误 ===
无
```

**0 个错误。**

## 4. 持久化

刷新页面后：

```
刷新后仍在主流程（localStorage 生效）: true
```

## 5. 功能点位（截图逐项核对）

| 功能 | 证据 |
|---|---|
| 绿色进度条 + `x/y` | 截图 01 显示 `1/10`，截图 03 显示 `3/10` |
| 校名自动识别 | 输入「北京邮电」→ 显示「北京邮电大学 · 211」，匹配方式标注为"校名" |
| 生成过渡 | 截图 07 显示 4 步递进 |
| 冲/稳/保 组合 | 截图 08 显示档位标签 + 门槛状态 + 理由 + 风险 + 来源链接 |
| 待核验提示 | 截图 08 顶部黄色横幅 |
| 流程图节点 | 截图 10 显示 6 阶段 + 状态 + 建议时间 + 材料计数 |
| 节点详情 | 截图 10 右侧显示材料清单 + 建议时间 + 官方截止日期「待核验」 |
| 材料勾选联动 | 截图 12 |
| 四栏导航 | 截图 13/14/15 |

## 6. 页面例外声明

按 AGENTS.md §6，纯前端页面/样式以浏览器实际效果验收，**未做前端 TDD / code review**。
本轮验收使用的就是上述截图与 `console` 检查。

## 6.1 Context7 复核发现的 CSS 层级 bug（已修复并复验）

按 AGENTS.md §1 用 Context7 复核 Tailwind v4 写法（`/tailwindlabs/tailwindcss.com`），发现两处与官方文档不一致：

| 项 | 官方写法 | 修复前 | 结果 |
|---|---|---|---|
| 设计变量位置 | `@theme { --color-*: ... }` | `:root { --brand: ... }` | 不生成工具类，已迁移 |
| 自定义组件类位置 | `@layer components` | 无层级 | **`.card` 的白色背景压过 `bg-*` 工具类**，已修复 |

**可复现证据**：修复前 `docs/screenshots/04-step5-gpa.png` 中「归一化结果」卡片为白色；
按官方结构修复并 `rm -rf .next` 重启后，同一截图渲染正确。

修复后 `make build` 通过、`make screenshots` 复跑通过、JS 错误仍为 0。

## 7. 本机运行

- 开发服务：`next dev` 在 `http://localhost:3000`，已实际启动并接受请求（HTTP 200）。
- 构建产物：`.next/` 已生成。

## 8. 未验证 / 未实现

| 项 | 状态 |
|---|---|
| 后端 FastAPI | **未开始**，不存在 |
| 服务端持久化 | **未实现**，当前只有 localStorage |
| Agent / 模型调用 | **未实现**，顾问分栏仅占位 |
| 官方截止日期 | **全部为「待核验」**，无真实数据 |
| `lib/` 纯函数单元测试 | **未写**（T4，已知缺口） |
| CI | **未配置** |
| 部署 / 容器 | **未验证** |
| 移动端 | 未在真机验证，仅做响应式布局 |
| 材料模板细分 | 未按学位/专业区分（T5） |

## 9. 与旧项目的关系

旧项目 `留学agent/web` 未做任何修改，仅作为只读参考与 Playwright 来源。
本阶段**没有复用旧代码**：骨架按新的产品形态重写，只沿用了领域对象的命名与"来源治理"的设计意图。
