# OfferPilot 重构本地评测报告

日期：2026-09-26
分支：`feature/offerpilot-mewhelp-fullstack`
评测方式：本地固定 fixture、当前 Python 环境；未调用在线 LLM、Milvus、Embedding API、Reranker 或 Langfuse 服务。

## StateGraph + Evidence Gate

数据集 SHA-256：`58a151ea4b43a3102487436cfd1ed4d74a0a49cb53c0d07a0eb5ec54a0d1f31c`
流程版本：`offerpilot-stategraph-v1`；检索：`official-knowledge-bm25-1.0.0`；门禁：`evidence-gate-v1`。

| 指标 | 结果 | 样本/口径 |
|---|---:|---|
| 固定用例 | 17 | 可回答 12、无答案 5 |
| 意图路由准确率 | 100% | 17 |
| 可回答问题 Top-1 命中 | 100% | 12 |
| Recall@5 | 100% | 12 |
| MRR@5 | 1.000 | 12 |
| 正确知识章节 Top-1 | 100% | 12 |
| Evidence Gate 可回答召回率 | 100% | 12 |
| Evidence Gate 无答案拒答准确率 | 100% | 4 个适用无答案用例 |
| Evidence Gate 错误放行数 | 0 | 4 个适用无答案用例 |
| 引用与答案 URL 覆盖率 | 100% | 12 个可回答用例 |
| 本地流程延迟中位数 | 2.221 ms | 17；不含在线模型/网络服务 |
| 本地流程延迟 P95 | 4.180 ms | nearest-rank，17 |

其余 1 个无答案用例走通用回复节点，不适用于官方事实证据门禁拒答统计。用例量小且来自项目内固定知识库，不能外推线上质量或宣称统计显著提升。

## 既有 Eval 基线复跑

| Eval | 样本 | 指标结果 |
|---|---:|---|
| RAG | 17（检索 12、无答案 5） | Top-1 项目 100%；Top-1 章节 100%；Recall@3 100%；引用覆盖 100%；无答案拒答准确率 100% |
| 推荐 | 10 | 硬约束准确率 100%；缺失信息准确率 100%；引用覆盖 100%；工具成功率 100%；平均运行 0.057 ms |
| Advisor | 24 | 工具选择准确率 100%；引用事实幻觉 0 |

这些是小型离线 fixture 上的本地基线/回归数据，不是生产数据，也不是重构前后对照增益。

## 验证结果

- API 测试：179 passed，6 skipped。跳过项依赖外部数据库服务，本次未执行。
- 前端 ESLint：通过。
- `docker compose ... config --quiet`：通过（使用 `.env.langfuse.example` 解析配置）。
- Docker daemon：未运行；因此没有启动或实测 Milvus、Langfuse、Embedding 服务及 Reranker。

Hybrid RAG 已有可选 Milvus + Dense/BM25 RRF + 可选 Reranker 代码路径，默认关闭并保留 BM25 回退。上述 100% 检索结果来自 BM25 固定 fixture，不能标成 Hybrid RAG 实测结果。Langfuse instrumentation 同样是可选、默认关闭，当前没有真实 trace 导出数据。
