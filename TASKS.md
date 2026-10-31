# LeapAshore 任务清单

> **执行规则**
> - 按顺序做：P0 → P1 → P2，上层没做完不开始下层；只卡在 MortyYJT 本人操作上的部分不算没做完。每做完一条就把 `[ ]` 改成 `[x]`，条目只留一行：任务名、PR 号、一个关键结果，后面链接到 `docs/measurements.md` 对应一节；测量结果、命令和注释（选了什么、为什么、什么没做或没验证）写进那一节（英文）。
> - 流程按 `CLAUDE.md`：大改动先写 OpenSpec；逻辑先 TDD；`make verify`；新上下文审查；CI 通过后合并。每条任务一个分支、一个 PR。
> - 已授权：AI 合并 PR；合并后 AI 部署（部署前备份生产库，部署后做线上只读检查，出问题就回滚；部署方式见 `docs/deploy.md`）。
> - 已批准：新依赖（celery、redis、langgraph-checkpoint-postgres、pgvector）；Alembic 改表（只加不删）；数据库镜像换成 `pgvector/pgvector:pg16`；compose 新增 redis、celery worker、celery beat；评估集里不调模型的部分进 CI。
> - **不要问 MortyYJT。** 所有选择（包括清单没写到的设计选择）都由 AI 自己决定，写进 `docs/measurements.md` 对应一节，并记进 `note/decisions.md`，标「Claude 自主（待 MortyYJT 复核）」。这是 MortyYJT 2026-10-30 的明确授权，执行本清单期间覆盖 `CLAUDE.md` 的「Ask the user first」。MortyYJT 回来看到不对会再改。
> - **卡住就跳过，不要停下来等。** 只有 MortyYJT 本人能做的（开账号、填密钥、加 DNS、提供 key），先做完其余部分，在 `docs/measurements.md` 对应一节写明卡在哪，继续往下做；`note/handoff.md` 里也写一份。
> - 学校范围（2026-10-29 定）：美国、英国、澳大利亚、加拿大、新西兰、中国香港、中国澳门、新加坡、韩国、马来西亚，欧洲 16 国（德、荷、瑞士、法、比、瑞典、意、西、爱尔兰、丹麦、挪威、奥地利、芬兰、葡萄牙、捷克、波兰），中东 3 国（阿联酋、沙特、卡塔尔），共 287 所。

## P0：最先修

- [x] **修复个人网站 mortyyjt.site** — PR #28。`mortyyjt.site` 200、`www` 301。[详情](docs/measurements.md#fix-the-personal-site-mortyyjtsite-pr-28)
- [x] **按新范围收缩学校库** — PR #34。346 → 287 所，生产范围外项目 0。[详情](docs/measurements.md#shrink-the-school-list-to-the-new-scope-pr-34)
- [x] **账号与登录（邮箱 + 验证码），砍掉背景测评** — PR #36（代码已上线，登录模式未开，等 MortyYJT 在服务器填个人邮箱的 SMTP 授权码）。并发首次登录只建 1 个账号，猜码第 5 次起作废。[详情](docs/measurements.md#accounts-and-sign-in-email--code-background-assessment-removed-pr-36)
- [x] **修顾问检索：先测基线，再改** — PR #38。报数组 Recall@4 0.10 → 0.889，误拦 0.60 → 0。[详情](docs/measurements.md#fix-advisor-retrieval-baseline-first-then-change-pr-38)
- [x] **顾问接口限流与额度** — PR #40、#44。限流检查 p99 5.61 ms（50 并发），伪造转发头无效。[详情](docs/measurements.md#advisor-rate-limits-and-quotas-pr-40-follow-up-pr-44)
- [x] **抽取写成代码**（`app/collect/extract.py`）— PR #42（离线工具）。10 校 95 页拒收率 10.3%。[详情](docs/measurements.md#extraction-as-code-appcollectextractpy-pr-42-offline-tool)
- [x] **仓库清理** — PR #43。移植说法 0 处，加 MIT LICENSE。[详情](docs/measurements.md#repository-clean-up-pr-43-docs-and-comments-only)
- [x] **跑 `make verify` + 查生产库** — PR #46。口径统一后「有要求」4,383 → 4,815，生产和采集文件逐项一致。[详情](docs/measurements.md#unify-the-requirement-count-and-check-production-pr-46)

## P1：核心升级（按顺序做）

- [x] **截止日期和学术要求入库** — PR #48。3,986 条截止日期、4,831 个学术要求入库，重导 0 写入。[详情](docs/measurements.md#deadlines-and-academic-requirements-pr-48)
- [x] **采集队列 + 变更检测** — PR #50、#51、#52、#54。补采 3,628 页，模型费 36.37 元；生产「有要求」7,545（P1 第六条重导后为 7,374）。[详情](docs/measurements.md#collection-queue-and-change-detection-pr-50-queue-code-pr-51-data-pr-52-review-pr-54-second-round)
- [x] **对话持久化** — PR #56。等待确认时 `kill -9` 重启后确认，只写一次。[详情](docs/measurements.md#conversation-persistence-pr-56)
- [x] **混合检索** — PR #58（全文 + 管线；**向量部分卡在 MortyYJT 的硅基流动 key**）。报数组 Recall@4 0.8958 → 0.9583（只用全文）。[详情](docs/measurements.md#hybrid-retrieval-pr-58-vector-part-waiting-for-the-owners-siliconflow-key)
- [x] **快照 RAG** — PR #60。引文核对通过率 82/82，不可答 6/6 拒答。[详情](docs/measurements.md#snapshot-rag-pr-60)
- [x] **概括忠实度校验** — PR #62。字段越界检出 81.5%，误伤 6.8%；**125 个项目和中国学生要求 2,278 条等 DeepSeek 充值后补判**。[详情](docs/measurements.md#summary-faithfulness-check-pr-62)
- [x] **忠实度评估扩样**（490 个字段，Claude 盲标、不人工复核）— PR #83。检出 103/147（70.1%），误伤 27/343（7.9%），精确率 103/130。[详情](docs/measurements.md#summary-faithfulness-evaluation-second-set-pr-83)

## P2：有余力再做

- [x] **知识缺口审核队列** — PR #67（另：PR #65 模型不可用时的降级）。记录一次拒答 p99 2.23 ms。[详情](docs/measurements.md#knowledge-gap-review-queue-pr-67-also-pr-65-degrading-when-the-model-is-unavailable)
- [ ] **可观测性**：接入 Langfuse Cloud，记录每轮对话的 token、耗时和工具调用，算出单轮平均成本。需要 MortyYJT 提供 key；没有 key 就跳过这条；不上报用户标识和邮箱。
  - 注：没有 key，按清单跳过；需要 MortyYJT 提供 Langfuse Cloud key 后再做（10-30 查过：本机和生产 `deploy/.env` 都没有 Langfuse 的 key）。
- [x] **人工核验入口** — PR #69。数据库触发器 + 静态扫描保证只有管理员确认能写 `verified_at`。[详情](docs/measurements.md#manual-verification-entry-pr-69)
- [x] **顾问检索评估 v2：分级标注 + nDCG/MRR**（MortyYJT 10-31 加，为开向量后的四路对比做准备）— PR #84。369 题，报数组 253 道要求题：全文 nDCG@4 0.524、MRR 0.519，规则 0.446、0.394，误放 0/26；标注由 Claude 写、不做人工复核。[详情](docs/measurements.md#advisor-retrieval-evaluation-v2-graded-set-and-rank-aware-metrics-pr-84)
- [ ] **界面收尾**：做完 `ledger-redesign` 剩下的 6 项（4.4、5.12、7.1、7.2、7.3、7.5）。

## 不做

- Kafka、RabbitMQ、Milvus、Elasticsearch、本地 embedding 模型、微服务、K8s、微调、多 agent。
