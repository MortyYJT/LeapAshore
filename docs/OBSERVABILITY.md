# OfferPilot 最小可观测性

OfferPilot 先固定可验证的 span 与 metric 语义，再决定是否接入 OpenTelemetry Collector 或托管监控。当前实现不依赖外部监控服务，也不代表已经得到线上 SLO、DeepSeek 实网延迟或容量结论。

## Trace 边界

每个 HTTP 请求接受合法的 W3C `traceparent`；缺失或非法时生成新的 128-bit trace ID。响应返回 `X-Trace-ID`。客户端提供的 `X-Request-ID` 只有在匹配 1–80 位字母、数字及 `._:-` 时才会沿用，否则服务端重新生成。结构化 span 只记录受控的低基数字段，不记录请求正文、用户 ID、邮箱、顾问消息、项目 slug 或异常消息。

| 层 | span | 说明 |
| --- | --- | --- |
| HTTP | `http.request` | 方法、FastAPI 路由模板、状态码、请求 ID |
| Agent | `advisor.plan`、`advisor.actions.plan` | 顾问规划与白名单动作选择 |
| RAG | `rag.retrieve` | 官方知识 BM25 检索 |
| Provider | `provider.plan`、`provider.stream` | 可选模型规划与流式调用；错误只记录异常类型 |
| Store | `store.<operation>` | 当前存储适配器的读写操作，不采集参数或返回值 |

`TELEMETRY_SPAN_SAMPLE_RATE` 控制结构化 span 日志采样，范围为 `0`–`1`，默认 `1`。指标始终累计，不受日志采样影响。

## Prometheus 指标

- `offerpilot_http_requests_total{method,route,status_class}`
- `offerpilot_http_request_duration_seconds{method,route,status_class}`
- `offerpilot_operation_total{layer,operation,outcome}`
- `offerpilot_operation_duration_seconds{layer,operation,outcome}`
- `offerpilot_rag_queries_total{outcome}`
- `offerpilot_rag_top_relevance_score{outcome}`
- `offerpilot_postgres_connection_slot_wait_seconds`
- `offerpilot_postgres_transaction_duration_seconds{outcome}`
- `offerpilot_postgres_advisory_lock_wait_seconds{outcome}`

HTTP `route` 使用 FastAPI 路由模板；未匹配请求统一标记为 `__unmatched__`，预路由拒绝标记为 `__pre_route__`，避免把用户 ID、资源 ID 或任意 URL 片段变成指标标签。

RAG 的 `outcome` 只有 `hit` 与 `no_answer` 两种固定值。每次官方知识检索恰好记录一次结果；最高 BM25 分数使用固定桶 `0/4/8/16/32/64/+Inf` 聚合，可计算拒答比例并观察分数分布。指标不记录查询文本、用户标识、项目 slug、命中正文或来源 URL。

PostgreSQL 指标同样只使用固定标签。`connection_slot_wait` 记录请求等待当前单连接适配器进程内互斥锁的时间，不是新建 TCP 连接耗时；`transaction_duration` 覆盖显式事务的成功/失败时长；`advisory_lock_wait` 覆盖数据库执行 advisory lock 获取语句的总等待与往返时间。锁键、用户 ID、run ID、来源版本 ID 和 SQL 均不会进入指标。应先用这些分布确认连接槽或数据库锁确实形成排队，再决定是否引入连接池/async DB；不能从本地小流量样本外推生产容量。

指标端点为 `GET /internal/metrics`。未配置 `METRICS_BEARER_TOKEN` 时返回 404；配置后只接受精确的 `Authorization: Bearer <token>`，并使用常量时间比较。示例：

```bash
curl -H "Authorization: Bearer $METRICS_BEARER_TOKEN" \
  http://127.0.0.1:8000/internal/metrics
```

## 当前边界与下一步

- 指标保存在单进程内存中，进程重启会清零，多实例也不会自动聚合。
- 当前没有声称已部署 Collector、Dashboard 或告警路由；接入时应直接抓取上述端点，并按 `trace_id` 关联 JSON span。
- 文档中的 API 可用性 99.5%、非 LLM API p95 小于 500ms 仍是待压测校准的初始目标，不是当前实测结果。
- RAG 指标目前只提供检索次数、拒答结果与相关度分布；没有真实查询基线前不设置告警阈值，也不把固定 Eval 分数当线上检索质量。
- PostgreSQL 的连接槽等待、事务与 advisory lock 分布已经可采集，但当前仍没有生产相似负载样本、连接池、Dashboard 或告警阈值。
- 下一步应在真实 PostgreSQL 与可控 Provider 测试环境中采样上述数据库分布以及 TTFT、完成率和 fallback 比例，再决定连接池/async DB，并建立 dashboard 与告警。
