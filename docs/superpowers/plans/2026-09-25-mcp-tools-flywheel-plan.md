# MCP Tools and Knowledge Flywheel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the MewHelp-style typed tool registry, MCP boundary, confidence fallback, and human-reviewed knowledge flywheel without allowing model-controlled writes.

**Architecture:** Keep pure recommendation and source functions as in-process tools. Define one typed registry shared by LangGraph and MCP adapters. MCP initially exposes only scoped read operations. Side effects are returned as proposed actions and require an authenticated confirmation endpoint with request revision and idempotency key. Low-confidence questions become review candidates and only existing source-governance approval can publish facts.

**Tech Stack:** LangChain tool schemas, MCP Python SDK, FastAPI, MySQL Agent review projection, PostgreSQL source governance, existing `safe_tool_actions` and store contracts.

**Spec:** `docs/superpowers/specs/2026-09-25-mewhelp-full-stack-rebuild-design.md`

## Global Constraints

- Tool names, schemas, permissions, timeouts, retries, and side effects are explicit allowlist entries.
- MCP server identity is not user identity; every request still carries verified caller scope from FastAPI.
- No model can commit a task, portfolio change, email, or source approval directly.
- User confirmation binds to the action payload hash, thread revision, and idempotency key.
- Flywheel output is untrusted candidate text until human source verification and PostgreSQL approval.

## Review Focus

- Unknown tool, extra argument, cross-user ID, stale revision, or missing confirmation fails closed.
- Duplicate confirmation returns the original outcome without repeating the action.
- MCP timeout, malformed JSON, malicious resource, or server disconnect cannot bypass evidence gate.
- Low-confidence question normalization cannot auto-create published facts or fabricate citation metadata.
- Review rejection, stale source, or failed Milvus projection remains visible and retryable.

---

### Task 1: Define registry and typed tool contracts

**Files:**
- Create: `api/app/tools/__init__.py`
- Create: `api/app/tools/contracts.py`
- Create: `api/app/tools/registry.py`
- Create: `api/tests/test_tool_registry.py`
- Modify: `api/app/services/agent.py`, `api/app/services/deepseek_advisor.py`

**Interfaces:** Each `ToolSpec` defines `name`, JSON schema, `permission`, `side_effect`, `timeout_seconds`, `idempotent`, and typed handler. `ToolResult` contains status, safe summary, and source/evidence IDs only.

- [ ] Add tests for unique tool names, schema rejection, permission denial, timeout, and handler exception redaction.
- [ ] Register deterministic profile read, program search, official knowledge search, GPA check, prerequisite check, and task/action proposal tools.
- [ ] Adapt LangGraph calls and existing `safe_tool_actions` to the registry without changing current mutation policy.
- [ ] Run `cd api && pytest -q tests/test_tool_registry.py tests/test_api.py`.

### Task 2: Add MCP server and client adapter for read-only tools

**Files:**
- Create: `api/app/tools/mcp_client.py`
- Create: `mcp_servers/offerpilot_readonly.py`
- Modify: `compose.yaml`, `compose.production.yaml`, `api/app/settings.py`
- Create: `api/tests/test_mcp_tools.py`

**Interfaces:** MCP transport uses a private service URL and scoped server credential. Client method `call_read_tool(name, arguments, caller_scope)` permits only registry names tagged read-only.

- [ ] Add tests for unknown tool, write-classified tool, invalid caller scope, oversized result, and MCP timeout.
- [ ] Implement only catalog, published-source lookup, and retrieval tools in the first server.
- [ ] Add private network/health check and credential rotation settings; do not expose an unauthenticated host port.
- [ ] Verify prompt-injection text returned by an MCP tool is treated as evidence text and cannot change graph routing.
- [ ] Run MCP unit tests and a local disposable service smoke test.

### Task 3: Add confirmed action proposal and commit flow

**Files:**
- Modify: `api/app/main.py`, `api/app/models.py`, `api/app/store.py`
- Create: `api/app/tools/actions.py`
- Modify: `api/tests/test_api.py`, `api/tests/test_store.py`
- Modify: `app/portfolio-controls.tsx`, `app/roadmap-view.tsx`

**Interfaces:** `AdvisorActionProposal` binds `action_id`, `thread_id`, `expected_revision`, `payload_hash`, `expires_at`, and safe display text. `POST /me/advisor/actions/{action_id}/confirm` requires the same authenticated owner and an idempotency key.

- [ ] Add a failing API test proving a model-generated `create_task` proposal does not write before confirmation.
- [ ] Add a test that a different user, expired proposal, changed payload, or stale thread revision receives a conflict/authorization failure.
- [ ] Implement proposal persistence and confirmation transaction using current CAS/idempotency records.
- [ ] Add UI confirmation card and explicit success/failure state; never auto-confirm on stream completion.
- [ ] Add replay test proving a repeated confirmation returns the original task ID and creates one task.
- [ ] Run API tests and browser E2E for proposal, cancel, confirm, and duplicate-confirm cases.

### Task 4: Implement confidence fallback and review flywheel

**Files:**
- Create: `api/app/services/confidence.py`
- Create: `api/app/services/flywheel.py`
- Create: `api/app/api/review.py`
- Create: `api/tests/test_confidence.py`, `api/tests/test_flywheel.py`, `api/tests/test_review.py`
- Modify: `api/app/main.py`, `api/app/source_governance.py`, `app/source-review-panel.tsx`

**Interfaces:** `compute_evidence_confidence(query, hits) -> ConfidenceResult`; `normalize_candidate(raw_question, retrieved_evidence) -> ReviewCandidate`; approval creates a source-version candidate through the existing source governance API and cannot publish without a source reviewer.

- [ ] Add tests for empty evidence, conflicting sources, stale source, one strong hit, and multiple weak hits.
- [ ] Add tests for normalization duplicate, malformed model output, hallucinated source ID, and no-answer routing.
- [ ] Store redacted candidate, retrieval/source-version snapshot, occurrence count, and provenance in MySQL; avoid storing raw applicant profile.
- [ ] Add review actions for approve-for-source-review and reject; do not add a direct publish shortcut.
- [ ] Test approval to candidate to PostgreSQL review to published event to Milvus projection as one traceable lifecycle.
- [ ] Run API/RAG Eval and browser review E2E; verify no candidate can answer until publication completes.
