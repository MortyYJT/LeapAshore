# OfferPilot MewHelp Full Stack Migration Roadmap

> **For agentic workers:** Follow the focused plan for each workstream. Execute one task at a time, keep the checkboxes current, and obtain an independent review at each phase gate.

**Goal:** Add the complete MewHelp Agent stack to OfferPilot in reversible, measurable slices while preserving existing product behavior and source governance.

**Architecture:** Keep Next.js and the current FastAPI product API. Add LangChain/LangGraph within the existing API, MySQL for Agent-domain records, Milvus for indexes derived from approved PostgreSQL facts, MCP for explicitly bounded tools, Langfuse for redacted traces, and an offline classifier/ONNX service. PostgreSQL remains authoritative for identity, profiles, published program facts, and source review.

**Tech Stack:** Next.js/React/vinext, FastAPI/Uvicorn, Pydantic Settings, `uv`, LangChain (`langchain-openai`, `langchain-mcp-adapters`, text splitters), LangGraph/AsyncSqliteSaver, SQLAlchemy asyncio/asyncmy, MySQL 8, pymilvus/Milvus Standalone, etcd, MinIO, BM25, BGE-M3-compatible embeddings, RRF, Cross-Encoder reranking, MCP, Langfuse, PostgreSQL, ClickHouse, Redis, PyTorch, Transformers, scikit-learn, tokenizers, ONNX/ONNX Runtime.

**Spec:** `docs/superpowers/specs/2026-09-25-mewhelp-full-stack-rebuild-design.md`

## Global Constraints

- PostgreSQL remains authoritative for identity, applicant profiles, published program facts, source history, and source review status.
- Do not remove existing deterministic recommendation, consent, redaction, idempotency, CAS revision, restore, or rollback behavior.
- MySQL, Milvus, Langfuse, and LangGraph checkpoints store Agent-domain or derived data only; each derived store must be rebuildable or replayable.
- Only approved official knowledge may enter Milvus; every answer about program requirements must cite the approved source/version.
- Keep cloud-provider calls behind existing consent and redaction checks; never silently change provider or send data after consent is withdrawn.
- No LLM or classifier may make final admission decisions, change hard constraints, or execute a side effect without user confirmation.
- Set quality thresholds from OfferPilot baselines and labeled evaluation data; do not copy MewHelp numeric claims.
- Never commit credentials, private conversations, raw applicant records, trained model files, or production data.

## Review Focus

- Concurrent and replayed Agent turns: assert CAS rejects stale writes and Idempotency-Key does not repeat side effects.
- Consent withdrawal during an in-flight turn: assert the next provider call is blocked and local fallback remains available.
- Stale, withdrawn, or superseded source versions: assert Milvus results are filtered or removed before they reach generation.
- Prompt injection in retrieved documents and MCP tool results: assert workflow policy and tool allowlists remain authoritative.
- MySQL, Milvus, Langfuse, or classifier outage: assert bounded timeout, visible degraded status, and deterministic fallback.

---

## Plan Set and Dependencies

Independent subsystems have focused implementation plans. Work proceeds in this order; a later plan must not bypass an earlier exit gate.

| Order | Focused plan | Entry condition | Exit condition |
|---|---|---|---|
| 0 | `2026-09-25-baseline-and-runtime-plan.md` | Approved architecture spec | Current behavior, data ownership, rollback and privacy baseline recorded |
| 1 | `2026-09-25-langgraph-agent-plan.md` | Plan 0 complete | Existing advisor behavior runs through a deterministic LangGraph path |
| 2 | `2026-09-25-mysql-agent-store-plan.md` | Plan 0 schemas and ownership map complete | Agent-domain MySQL storage reconciles and restores; PostgreSQL remains source of truth |
| 3 | `2026-09-25-milvus-hybrid-rag-plan.md` | Plan 0 corpus and Eval baseline complete | Milvus shadow retrieval meets or beats approved RAG gates |
| 4 | `2026-09-25-mcp-tools-flywheel-plan.md` | LangGraph tool contracts stable | Read tools are bounded; writes require user confirmation; approved knowledge alone is published |
| 5 | `2026-09-25-langfuse-eval-plan.md` | Trace field allowlist approved | Redacted trace and per-stage Eval are usable; no forbidden payload is captured |
| 6 | `2026-09-25-classifier-onnx-plan.md` | Taxonomy and real labeled-data policy approved | ONNX candidate classifier meets held-out gates; otherwise remains offline |
| 7 | `2026-09-25-cutover-operations-plan.md` | Plans 1–6 reviewed and feature-gated | Restore, rollback, gray release, and operations acceptance complete |

### Program checkpoints

1. **Freeze baseline:** Run the current backend/frontend checks, Agent/RAG Evals, PostgreSQL integration and restore smoke. Record command output, versions, timings, environment, and known skipped checks.
2. **Build workflow:** Add LangChain/LangGraph adapters and run the deterministic path in shadow mode. Do not change response or write semantics yet.
3. **Add stores and retrieval:** Build the MySQL Agent store and Milvus index as replayable projections. Reconcile counts and hashes against PostgreSQL before any read traffic.
4. **Add tools and feedback loop:** Register each read tool; expose MCP only where a separate process/client is required. Present every write action for user confirmation. Send knowledge candidates through the existing source-version review flow.
5. **Add telemetry and classifier:** Deploy Langfuse with explicit field allowlist and retention. Train/evaluate the classifier offline before any routing flag can enable it.
6. **Cut over gradually:** Shadow, staff-only, limited Beta, and broader release. For each step compare business outputs, citations, refusal behavior, latency, cost, and side-effect counts. Keep one-click feature flags for old paths.

### Whole-program acceptance

- Existing frontend tests, API tests, Agent Eval, RAG Eval, PostgreSQL concurrency tests, and restore smoke pass with no unexplained skips.
- Every approved fact answer includes source URL, publication/version context, and freshness data; unsupported facts return the existing honest no-answer response.
- Shadow and gray traffic show no recommendation hard-constraint regression, unauthorized data egress, duplicate side effect, or stale-source answer.
- Backup/restore is proven for PostgreSQL, MySQL, Milvus metadata/object volumes, and SQLite checkpoint volume; Langfuse retention/deletion behavior is documented.
- Rollback to the current deterministic/DeepSeek paths is rehearsed and does not require a destructive data migration.

## Shared Commands

Run commands from the indicated directory; use environment variables from a dedicated test environment and never print secret values.

```bash
# Frontend, from web/
pnpm test
pnpm run lint
pnpm run test:e2e

# API unit tests and static evals, from web/api/
pytest -q
python -m evals.run_eval
python -m evals.run_rag_eval
```

Database and Docker integration commands are defined in the focused plans because they require explicit ephemeral service configuration.
