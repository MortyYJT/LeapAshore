# OfferPilot 参照 MewHelp 全栈升级重构规格

## 1. 目标与依据

把 MEWHELP 的教学项目能力完整移植到 OfferPilot，覆盖模型接入、意图与上下文管理、工作流编排、检索、工具、观测、评估、数据飞轮及分类器训练。MEWHELP 是技术参考，不是留学业务规则来源；所有招生事实仍须来自 OfferPilot 已登记并通过审核的官方资料。

用户选择路径 A（字面全栈复制）。因此计划须纳入 MySQL、Milvus、LangChain、LangGraph、MCP、Langfuse、混合检索与重排、以及独立主题分类器训练/ONNX 推理链路。OfferPilot 当前 PostgreSQL、Alembic、来源治理和认证仍在使用；规格要求采用并行数据平面和分阶段切换，禁止在第一阶段删除或迁移掉现有权威数据。

依据：Edge 中的 MewHelp「理论学习：全链路串联与踩坑复盘」；`~/Desktop/MEWHELP python/README.md`、`pyproject.toml`、`DEPLOY.md` 与 `docs/superpowers/specs/` 下 ch02–ch10 设计；OfferPilot 的 `web/README.md`、`web/PRD.md`、`web/docs/RAG_ARCHITECTURE.md`、`web/docs/OBSERVABILITY.md`、`web/docs/BETA_LAUNCH_RUNBOOK.md` 及现有 `web/api/app/` 实现。

## 2. 当前基线

- 产品前端为 Next.js/React/vinext，Agent API 为 FastAPI/Pydantic。
- 产品业务数据保存在 PostgreSQL，使用 Alembic；应用已有 Store 抽象及并发/幂等保护。
- 推荐、GPA/语言/先修约束、项目筛选与动作计划主要由确定性 Python 逻辑执行；模型只负责有限解释。
- 官方项目事实由审核和版本化流程发布。RAG 使用 BM25 与中英别名，按学位/方向/项目过滤，并要求引用、核验日期和库外拒答。
- 模型数据处理需用户同意；进入云端前进行脱敏；模型不得修改硬门槛和已发布事实。
- 当前观测包含结构化 trace、低基数 Prometheus 指标和 Sentry 集成；尚无 Langfuse 部署。

## 3. 目标架构

保留 Next.js 产品层和现有 FastAPI 产品 API。在现有 Python 服务内逐步增建 LangGraph Agent 运行时；通过内部受认证 API 与前端/产品 API 连接，避免平行建立第二套用户认证。

数据职责分开：PostgreSQL 继续作为用户身份、申请档案、项目事实、来源版本和审核记录的权威库；MySQL 承载新 Agent 域的会话/消息副本、工作流审计、知识摄取任务、低置信问题与反馈审核队列；Milvus 保存由已发布事实构建的 dense 与 BM25 检索索引；LangGraph checkpoint 初版使用 MEWHELP 的 AsyncSqliteSaver 和持久卷。每个派生存储必须可由其权威源重建，记录来源版本及索引版本，不可反向覆盖已发布 PostgreSQL 事实。

主请求链路：

1. 校验身份、同意状态、请求幂等键和会话版本；构造最小化脱敏上下文。
2. 读取分层会话记忆并消解指代；保留来源于结构化 profile 的字段优先级和更新时间。
3. 意图识别与路由：申请规划、官方项目知识、背景补充、执行行动、闲聊/其他。分类器可作初筛，低置信或高影响请求交 LLM；最终工作流路由由确定性规则约束。
4. 规划类请求运行确定性 GPA、背景、先修课、语言及预算工具；模型只能解释工具结果。项目/政策知识请求强制检索已发布证据；无足够证据则拒答或请求人工核验。
5. 知识检索并行运行结构过滤、BM25 和向量召回，采用 RRF 合并；重排器只处理限量候选。输出携带官方 URL、版本、哈希与核验日期。
6. LangGraph 工作流汇总证据、工具结果、用户确认节点和安全检查后生成回答；任何数据库写操作、发送邮件或提交申请均作为需明确用户确认的动作提议，不由模型自动完成。
7. 流式输出与持久化沿用请求幂等、CAS revision 和部分写入恢复规则；记录 trace、模型/检索/工具耗时与成本。
8. 低证据/差评进入脱敏问题池，经去重、人工核准和来源复核后才能产生候选知识版本；候选经现有 PostgreSQL 来源审核发布后再增量同步 Milvus。

## 4. 技术映射

| MEWHELP 能力 | OfferPilot 采用方式 |
|---|---|
| FastAPI、Pydantic | 沿用现有 FastAPI API 和 Pydantic 契约 |
| LangChain / OpenAI-compatible provider | 增加可配置 chat、embedding、rerank provider；密钥仅服务端读取，保留显式同意和脱敏 |
| LangGraph StateGraph / ReAct | 作为有状态流程骨架；硬约束与写操作继续由确定性节点执行 |
| SQLAlchemy + MySQL | 用于新增 Agent 域工作库；PostgreSQL 保持产品权威源，明确同步方向与重建机制 |
| Milvus Standalone + etcd + MinIO | 按参考 compose 部署元数据、对象和向量服务；为已发布官方知识版本构建可重建的 dense 与 BM25 混合索引；不得索引草稿、用户私密资料或未经审核网页 |
| BGE-M3/兼容 embedding provider + Cross-Encoder reranker | embedding 与 rerank 独立配置、独立评估；精排只处理固定数量候选，未通过项目 Eval 前不作为唯一排序依据 |
| MCP 工具服务 | 先把边界稳定且确需独立部署的只读工具暴露为受控 MCP；工具名、参数、权限和副作用列白名单 |
| Langfuse | 私有部署或受控自托管；关闭原始输入/输出采集，按字段允许清单采集低基数脱敏属性 |
| 置信度闸门与数据飞轮 | 校准证据阈值；候选仅进审核队列，人工核验后更新 PostgreSQL 与检索索引 |
| PyTorch + Transformers + scikit-learn + ONNX Runtime | 离线语料构建、人工标注、训练、阈值扫描、ONNX 导出与独立推理作业；不在证据不足时自动作高影响路由决定 |
| SQLite checkpoint | 第一阶段单实例持久卷；多实例/生产耐久性验收前不得宣称高可用，单独记录恢复与备份策略 |
| Langfuse 自托管依赖栈 | 按参考部署 Langfuse web/worker、PostgreSQL、ClickHouse、Redis 和 MinIO；与 Milvus 的 MinIO 实例和存储卷隔离 |

模型名、供应商 URL、超时与限额由配置注入。Chat、embedding、rerank 可独立切换；没有明确配置时使用确定性流程，不隐式切换供应商或向云端发送资料。

## 5. 不可破坏的产品约束

- PostgreSQL 中身份、申请档案、已审核项目事实、来源历史和审核状态仍是权威数据；MySQL/Milvus/Langfuse/checkpoint 只能保存派生或 Agent 域数据。
- 迁移支持双读比对和可回滚切换；在备份恢复、数据一致性和线上影子评估通过前不移除现有实现。
- 不把目录入口当作课程级要求，不把匹配分描述为录取概率，不允许模型发明或更改门槛。
- 不把姓名、邮箱、账号 ID、原始成绩单、自由文本原话、访问令牌写入 Milvus、Langfuse 或指标标签；向量语料只来自审核发布知识。
- 外部工具默认只读；写操作需要用户逐项确认、幂等键、审计记录和可恢复结果。
- 保留确定性无模型路径、用户数据处理同意、超时/限流/余额不足降级和可见失败状态。
- 课程示例中的指标或阈值不能作为 OfferPilot 成效声明；每个质量门槛由本项目标注集和真实观测校准。

## 6. 分阶段方案与出口条件

### 阶段 0：基线、威胁边界与兼容性冻结

清点 API 契约、数据库表、备份与恢复、现有 Eval、流式协议、同意/脱敏边界及幂等/CAS；记录当前行为和部署资源上限。形成迁移清单、数据分类表和可回滚方案。出口：可在干净环境复现当前服务；现有关键 Eval 与 PostgreSQL 恢复检查通过。

### 阶段 1：工作流骨架与会话状态

加入 LangChain 与 LangGraph，建立纯确定性节点图：load profile、resolve context、classify intent、route、deterministic tools、evidence gate、response、persist/trace。先用兼容适配器复用现有推荐与 store 服务；两入口、SSE、恢复、CAS revision 和 Idempotency-Key 的契约不变。出口：固定场景节点路径与工具结果一致，模型关闭时旧流程仍能完整运行。

### 阶段 2：MySQL Agent 工作库与迁移

增加 SQLAlchemy/MySQL 独立服务配置、迁移、连接健康检查和备份恢复；定义唯一的数据所有者、事件 ID、源 revision、重放规则和删改策略。先双写影子表并校验对账，不将用户账户或审核事实迁出 PostgreSQL。出口：故障注入、重复请求、部分双写、恢复演练能证明无丢失/重复副作用，随后才可启用 Agent 工作数据的 MySQL 读路径。

### 阶段 3：知识摄取、Milvus 与混合检索

基于现有已发布版本生成 chunk；保存来源 ID、内容哈希、发布时间、核验时间与 embedding/rerank 模型版本。建立幂等构建、增量更新、删除/过期 tombstone、重建和 BM25+dense+RRF 检索。影子运行比较现有 BM25 与混合检索。出口：扩展后的 Eval 达到或超过现行 Recall@3、项目/章节准确率、引用覆盖、无答案拒答和过期来源命中门槛；不合格则继续使用现有 BM25。

### 阶段 4：证据校验、重排与安全回答

增加受限候选重排、证据置信度校准和不可绕过的知识回答闸门。验证模型只能引用提供的官方来源、无法以工具请求伪造审核通过状态。出口：库外拒答准确率和引用正确率达到 100% 的项目验收要求；端到端延迟与费用在批准预算内。

### 阶段 5：工具/MCP 与人工确认节点

抽取工具契约，先实现内部工具适配器，再按需要单独运行 MCP 服务。每个工具定义 schema、读写范围、超时、重试、授权、审计和幂等行为。将保存申请方案/建任务/邮件等副作用变成确认卡片，确认端点核验调用者和请求 revision。出口：未确认动作在任何分支都不执行；重放、越权、工具超时和工具结果注入用例通过。

### 阶段 6：Langfuse、评估和低置信度飞轮

建立 trace 采集字段 allowlist，关闭输入/输出正文记录；关联请求、图节点、检索、工具与 provider 的耗时/token/错误类型。扩展离线 Eval 和人工复核 UI/流程，问题归并不得自动写入正式知识。出口：从 Trace 能定位单次失败且不含禁采字段；核准知识经版本审核发布后可追溯同步到 Milvus。

### 阶段 7：分类器语料和 ONNX 服务

制定意图 taxonomy、冲突标签规则和标注手册；拆分训练/验证/测试集，训练并做阈值/混淆评估；ONNX 服务只提供带置信度的候选意图。低置信、高风险或分布外输入回退 LangChain/人工路径。出口：冻结留出集表现优于当前基线且各关键类别召回达标；不满足即不启用在线路由。

训练工具和推理服务使用与参考项目对应的 PyTorch、Transformers、scikit-learn、ONNX/ONNX Runtime、tokenizers；训练依赖与 API 在线最小依赖分组，避免把训练框架强制装进 Web 运行镜像。

### 阶段 8：灰度切换与运行验收

影子流量、内部用户灰度、受限 Beta、扩大流量依次推进；按错误率、延迟、拒答、引用、重复动作、成本与同意撤回影响设置停机门槛。完成数据库/索引/checkpoint 备份恢复，回滚到现有 Agent，并演练 provider/Milvus/MySQL/Langfuse 不可用降级。出口：关键 Eval、浏览器全链路、PostgreSQL 集成、恢复和隐私检查全部通过；有版本化回滚记录和运行手册。

## 7. 测量与验收

- 业务正确性：推荐门槛、先修/语言状态、申请组合与行动计划不得低于当前固定 Eval；结果可重放并保留 profile snapshot、workflow version、事实版本和来源。
- RAG：按项目和章节评估 Recall@3、MRR、引用覆盖/正确率、库外拒答、过期来源误命中；与 BM25 基线逐项比较。
- 工具：路由正确率、参数校验、成功率、重复副作用率、超时恢复和用户确认完整率。
- 体验/可靠性：TTFT、完整响应时间、错误率、降级率、线程恢复正确性；目标值需在阶段 0 测基线后确定，不臆造。
- 成本：按意图拆分模型与重排/嵌入成本；成本预算先由用户确认，再用于切流阈值。
- 隐私/安全：自动检查 Langfuse、应用日志、MySQL、Milvus 和指标中不得出现禁止字段；测试 prompt injection、检索文档指令、恶意工具返回和越权用户 ID。
- 每个阶段均需独立回归和 review；“服务启动”“模型返回文字”不等同于端到端验收。

## 8. 风险和需要在实施计划中明确的事项

1. MySQL 与 PostgreSQL 并行会产生双存储一致性、两套迁移、备份和运维负担；若实际没有明确 Agent 工作数据隔离需求，应在阶段 0 再确认分库必要性，但选择 A 的实施计划仍须包含 MySQL。
2. SQLite checkpoint 在多实例扩展、磁盘故障和并发上的限制必须通过明确的单实例部署约束、持久卷和备份处理；不得默认其具备数据库级高可用。
3. Milvus 的版本化索引与 PostgreSQL 发布审核需通过 outbox/reconciliation 保证最终一致；用户撤回/来源过期必须能在规定窗口内从检索结果撤除。
4. Langfuse 可能收集敏感对话；默认关闭原文采集并做字段 allowlist、访问控制、保留期限与删除验证。
5. LLM 意图分类和小模型标签漂移可误路由到高影响流程；硬门槛工具和人工确认点始终作最终权威。
6. 费用和服务数量会明显上升；阶段 0 需确认测试与生产所需最低资源、环境变量和运维负责人。

## 9. 范围外

- 不重新设计留学业务规则，不把客服订单/退款实体映射成录取规则。
- 不自动抓取并发布学校网页；官方资料采集仍走现有域名安全校验和人工审核。
- 不在本规格批准数据库删除、生产部署、公开发布、模型训练数据外发或用户资料迁移。
- 不预设准确率、延迟、成本改善；必须由 OfferPilot 评估与真实环境测量得出。
