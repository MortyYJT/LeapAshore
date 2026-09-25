# Native Implementation Progress — 2026-09-25

## Workspace and boundary

- Isolated checkout: `/tmp/offerpilot-mewhelp-fullstack`
- Branch: `feature/offerpilot-mewhelp-fullstack`, based on `9795a3de820a96d1068f882fce8088a1e989c090`.
- No commits, merge, push, deployment, or production database operation.
- Source checkout `~/Desktop/MEWHELP python/` was read as a reference; no source files were copied verbatim into OfferPilot.

## Implemented foundations

- **LangGraph:** versioned Pydantic state, deterministic routing, composable graph, handler injection, sync/async runtime adapters, SQLite checkpoint lifecycle and opaque checkpoint-reference guards. Current advisor HTTP handlers are still on the legacy path; no production request is routed through the placeholder graph.
- **Agent store/outbox:** SQLAlchemy asyncio/asyncmy models and repository, MySQL Alembic setup and private optional Compose profile; PostgreSQL `save_thread` writes a versioned, content-free projection event in its CAS transaction; leased outbox worker, bounded retries, projection and reconciliation CLI are present. Account deletion propagation, migration execution, real DB transaction rollback, live MySQL and full backup/restore remain unverified or unfinished.
- **Hybrid RAG:** published-source-only chunk builder, OpenAI-compatible embedding adapter with consent checks, Milvus 2.6 schema/upsert/search, dense + built-in BM25 fusion, freshness filtering and local TEI reranker adapters. These are not wired into current user-facing RAG routes; existing BM25 remains authoritative.
- **MCP:** private-host client guard, optional client disabled by default, Streamable HTTP server with official-facts search and allowlisted action proposals only. Proposals never execute side effects. Shared typed registry, authenticated caller scope propagation and actual service smoke test remain unfinished.
- **Langfuse privacy boundary:** added `safe_agent_attributes()` to accept only fixed enum and bounded count/latency fields; sentinel tests prove query, profile, email, source text and arbitrary exception strings are dropped. Langfuse SDK, exporter, callbacks, self-hosted service and evaluation report pipeline are not connected. Do not enable production Langfuse export yet.
- Added `.env.example` names and optional `agent-stack` Compose profile for MySQL, Milvus, TEI and MCP; no service host ports are published. Compose renders successfully. Runtime is not available because Docker daemon is unavailable.

## Verification run in this continuation

- `cd api && .venv/bin/pytest -q`: **160 passed, 6 skipped**. Skips are live PostgreSQL/MySQL tests requiring database URLs/services.
- `pnpm test`: build passed and **31/31** Node tests passed. This includes guarded restore smoke tests against the test harness, not a live application production restore.
- `pnpm lint`: passed.
- `cd api && .venv/bin/python -m evals.run_eval`: 10 cases; hard constraints, missing info, citations and tool completion all 1.0.
- `... -m evals.run_rag_eval`: 17 cases; top-one program/section, recall@3, citation coverage and no-answer accuracy all 1.0.
- `... -m evals.run_advisor_eval`: 24 cases; tool selection accuracy 1.0 and zero citation fact hallucinations.
- `docker compose --profile agent-stack config --quiet`: passed; services were not started.
- Earlier baseline E2E: 8 passed before implementation; not rerun in this continuation because UI code did not change.

## Remaining before a real migration or production enablement

- Complete graph service nodes and feature-flagged shadow comparison, then route existing sync/SSE handlers through a compatibility adapter only after API regression tests.
- Complete common typed tool registry, MCP authorization/scope boundary, user-confirmed action endpoint/UI and reviewable low-confidence knowledge flow.
- Wire hybrid retrieval to published-source projection and compare against current BM25 with a fixed eval before enabling.
- Implement privacy-reviewed Langfuse SDK filtering and self-hosted service; profile actual resource demand before deployment. Add workflow Eval reports and repeatable trend comparisons.
- Obtain a real, consented and correctly labeled dataset before classifier training/export; synthetic fixtures can test the pipeline but cannot demonstrate production accuracy.
- Finish DB migration, deletion propagation, actual MySQL/PostgreSQL/Milvus integration, restore/rollback and cutover rehearsal in disposable infrastructure; configure backups, retention, monitoring and rollback controls.
- Staff-only shadow observation, parity gates and a separately approved rollout remain ahead; no production cutover has occurred.
