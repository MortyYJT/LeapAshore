# Langfuse and Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add self-hosted Langfuse tracing and an evaluation/data flywheel that can diagnose Agent behavior without collecting private conversation contents.

**Architecture:** Keep current low-cardinality metrics and Sentry for service health. Add Langfuse as a separate protected trace store using an explicit event allowlist. Offline evaluations remain the quality authority; flywheel samples are redacted, reviewed, and cannot publish facts by themselves.

**Tech Stack:** Langfuse Python SDK, LangGraph callbacks, Docker Compose, PostgreSQL, ClickHouse, Redis, MinIO, pytest, fixed Agent/RAG Eval sets.

**Spec:** `docs/superpowers/specs/2026-09-25-mewhelp-full-stack-rebuild-design.md`

## Global Constraints

- Disable Langfuse input/output capture by default; emit only allowlisted low-sensitivity fields.
- Do not send PII, user IDs, raw queries, profile fields, source excerpts, credentials, or model response bodies to Langfuse.
- Keep existing Prometheus label cardinality and protected metrics endpoint unchanged.
- Metrics and Eval outcomes are distinct: static Eval score is not a production SLO.
- Langfuse unavailable must not fail a user request.

## Review Focus

- Streaming request spans stay open until response completion/cancellation and close on exceptions.
- Span/metric metadata never contains request body, user ID, email, conversation ID, project slug, or arbitrary exception text.
- Langfuse credentials are not returned from status endpoints or logs.
- Disabled Langfuse, backend outage, and timeout preserve current service response.
- Flywheel sample approval remains separate from official source publication.

---

### Task 1: Specify and test trace field allowlist

**Files:**
- Create: `api/app/observability_fields.py`
- Modify: `api/app/observability.py`
- Create: `api/tests/test_langfuse_privacy.py`
- Modify: `docs/OBSERVABILITY.md`

**Interfaces:** `safe_agent_attributes(state) -> dict[str, str | int | float | bool]` returns only fixed names and bounded values such as graph version, intent class, route class, node name, outcome, token count, latency, and error type.

- [ ] Add sentinel-data tests that pass fake email, account ID, profile text, query, source body, and exception message through every trace helper and assert none appears in captured export.
- [ ] Add tests for fixed label values and max attribute count/length.
- [ ] Implement allowlist serialization; drop unknown keys rather than serializing generic state.
- [ ] Run `cd api && pytest -q tests/test_observability.py tests/test_langfuse_privacy.py`.

### Task 2: Deploy isolated Langfuse stack

**Files:**
- Create: `compose.langfuse.yaml`
- Create: `.env.langfuse.example`
- Modify: `compose.yaml`, `compose.production.yaml`, `docs/OBSERVABILITY.md`
- Create: `api/tests/test_langfuse_settings.py`

**Interfaces:** Langfuse is optional via `LANGFUSE_ENABLED`; SDK configuration requires endpoint, project key, secret key, and bounded flush timeout from secret environment.

- [ ] Define a dedicated Langfuse Compose project with pinned supported images for web/worker, PostgreSQL, ClickHouse, Redis, and a MinIO instance with independent volumes.
- [ ] Bind admin-only ports to localhost/private network; require generated secrets and reject known sample secrets in production.
- [ ] Add settings tests for disabled mode, partial credentials, unsafe public binding, and valid configuration without printing secrets.
- [ ] Add health/readiness checks and data retention/deletion notes.
- [ ] Start the stack only in a disposable development environment and verify health; do not connect production traffic in this task.

### Task 3: Attach callbacks to graph and test degradation

**Files:**
- Modify: `api/app/graph/runtime.py`, `api/app/observability.py`, `api/app/settings.py`
- Create: `api/tests/test_langfuse_callback.py`

**Interfaces:** `build_trace_callback(enabled, safe_metadata)` returns an optional SDK callback; callback inputs are filtered before SDK construction. Flush is bounded and errors are swallowed after structured local error-type logging.

- [ ] Add tests proving graph state/message objects never reach the callback as serialized input/output.
- [ ] Add tests for callback disabled, SDK error, timeout, stream cancellation, and normal trace end.
- [ ] Attach trace ID correlation without user identifiers or raw prompt text.
- [ ] Run the callback tests and current observability tests; verify current metric outputs remain unchanged.

### Task 4: Add evaluation trend and reviewable flywheel reports

**Files:**
- Modify: `api/evals/run_eval.py`, `api/evals/run_rag_eval.py`
- Create: `api/evals/run_workflow_eval.py`, `api/evals/data/workflow_cases.json`
- Create: `api/app/services/eval_reports.py`
- Create: `api/tests/test_eval_reports.py`
- Modify: `docs/OBSERVABILITY.md`

**Interfaces:** Each report stores dataset hash, workflow/retrieval/prompt versions, metric values, run time, and trigger; no user text. Eval runner consumes only committed fixture sets or explicitly redacted, approved samples.

- [ ] Add workflow cases asserting node path, tool execution, source citation, confidence gate, and no-answer routing.
- [ ] Add report schema and tests for missing metrics, version mismatch, and trend comparison with no prior run.
- [ ] Add a CLI report command that produces JSON/Markdown from one Eval result without recomputing metrics in the UI.
- [ ] Add review sampling instructions and data retention limits; do not use raw live traces as training data.
- [ ] Run Agent, RAG, and workflow Eval twice and verify the second run produces a comparable versioned trend.
