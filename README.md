# OfferPilot 留学罗盘

一个开源的留学申请规划 Demo。用户填写学术背景和申请目标后，系统使用透明规则对澳大利亚 Group of Eight 院校进行冲刺、匹配和稳妥分档。

> 当前版本用于产品验证，不构成录取承诺。具体要求应以各大学具体课程官网为准。

## 功能

- Demo 账户登录流程
- 结构化申请背景表单
- 澳洲八大选校推荐
- 可解释的匹配分、理由和风险提示
- 学校详情与下一步行动建议
- 独立 FastAPI 推荐接口示例

## 本地运行前端

需要 Node.js 22.13 或更高版本。

```bash
pnpm install
pnpm dev
```

访问 `http://localhost:3000`。

## 本地运行 FastAPI

需要 Python 3.12 或更高版本。

```bash
cd api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

接口文档位于 `http://localhost:8000/docs`。

## 项目结构

```text
app/            Next.js / Vinext 前端
api/            FastAPI 后端
PRD.md          MVP 产品需求文档
```

## 推荐算法

Demo 使用可解释的规则引擎，综合标准化 GPA、院校背景、目标方向和语言准备度生成“匹配分”。它不是录取概率。规则位于前端页面与 `api/app/services/recommender.py`，便于后续替换为统一配置或模型服务。

## 数据来源

- [Group of Eight 官方成员名单](https://go8.edu.au/about/the-go8)
- 各大学官方网站

学校数据最近核验日期：2026-07-14。

## 后续路线

- 接入 Supabase Auth 和 PostgreSQL
- 从学校级推荐升级为具体项目级推荐
- 增加数据来源审核、过期提醒和管理后台
- 支持申请时间线与材料清单

## License

MIT
