# LangGraph Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route OfferPilot advisor turns through a stateful LangGraph workflow while preserving current contracts and deterministic business decisions.

**Architecture:** LangChain owns provider/structured-output adapters; LangGraph owns state and routing. Existing recommendation, privacy, store, and action helpers remain authoritative nodes behind adapters. Enable the graph in shadow mode before allowing it to produce user-visible output.

**Tech Stack:** LangChain, LangGraph, FastAPI, Pydantic, current `ModelProvider`, existing repository/Store adapters, AsyncSqliteSaver for the initial single-instance checkpoint.

**Spec:** `docs/superpowers/specs/2026-09-25-mewhelp-full-stack-rebuild-design.md`

## Global Constraints

- Cloud model calls remain inside the consented and redacted streaming boundary.
- Recommendations and all write actions remain deterministic and validated by existing services.
- Preserve `Idempotency-Key`, thread revision CAS, SSE event contracts, and explicit model failure behavior.
- Use a bounded maximum graph step count and explicit timeout on each provider/tool call.

## Review Focus

- A replayed turn cannot apply profile/task/portfolio side effects twice.
- A stale thread revision returns the same conflict semantics as the current API.
- Consent revoked mid-turn prevents any subsequent provider call.
- Missing checkpoint, corrupt checkpoint, and checkpoint restart each return a recoverable state or visible error.
- An agent/tool loop reaching its step limit never emits an unvalidated intermediate tool result as the final answer.

---

### Task 1: Add versioned workflow state and deterministic node contracts

**Files:**
- Create: `api/app/graph/__init__.py`
- Create: `api/app/graph/state.py`
- Create: `api/app/graph/nodes.py`
- Create: `api/app/graph/routing.py`
- Create: `api/tests/test_agent_graph.py`
- Modify: `api/pyproject.toml`, `api/requirements.txt`

**Interfaces:** `AdvisorState` carries `user_id`, `thread_id`, `request_id`, `expected_revision`, `profile_snapshot`, `messages`, `intent`, `route`, `recommendation`, `knowledge_evidence`, `proposed_actions`, `citations`, `provider_usage`, `errors`, and `final_reply`. Nodes accept and return partial state mappings.

- [ ] Add a failing test that a state with an unsupported `schema_version` is rejected before graph execution.
- [ ] Run `pytest -q tests/test_agent_graph.py` from `web/api/`; confirm the test fails before implementation.
- [ ] Add the typed state and pure deterministic route helpers. Define bounded intent classes: planning, official knowledge, profile clarification, action, and other.
- [ ] Add tests for each intent boundary, ambiguous intent, missing profile, and high-impact route forcing a deterministic node.
- [ ] Run `pytest -q tests/test_agent_graph.py` from `web/api/`; require all state and routing cases to pass.

### Task 2: Compose graph from current services

**Files:**
- Create: `api/app/graph/build.py`
- Create: `api/app/graph/runtime.py`
- Modify: `api/app/main.py`, `api/app/services/agent.py`, `api/app/services/advisor.py`
- Test: `api/tests/test_api.py`, `api/tests/test_model_provider.py`, `api/tests/test_agent_graph.py`

**Interfaces:** `build_advisor_graph(checkpointer)` returns a compiled graph. `run_advisor_turn(state, *, stream, configurable)` adapts current sync/stream routes to graph input/output without changing response models.

- [ ] Add a graph integration test using fake deterministic nodes and assert ordered node events.
- [ ] Verify the integration test fails before the graph builder exists.
- [ ] Build nodes for load snapshot, resolve context, classify, route, retrieve official facts, run deterministic recommendation/action helpers, evidence gate, compose reply, and persist.
- [ ] Route both existing `/me/advisor` message handlers through the compatibility adapter behind `ADVISOR_GRAPH_ENABLED=false` by default.
- [ ] Preserve SSE frame names and thread revision/idempotency commits; add regression assertions to current API tests.
- [ ] Run `pytest -q` from `web/api/`; require legacy and graph-specific API tests to pass.
- [ ] Run both current Agent and RAG evals and compare emitted structured results with Task 1 baseline.

### Task 3: Add checkpointer and restart semantics

**Files:**
- Create: `api/app/graph/checkpoint.py`
- Modify: `compose.yaml`, `compose.production.yaml`, `api/app/settings.py`
- Test: `api/tests/test_agent_graph.py`, `api/tests/test_settings.py`

**Interfaces:** `create_checkpointer(settings)` returns an async SQLite saver for local/single-instance graph mode; checkpoint `thread_id` is scoped as an opaque internal thread key and must not include raw account identifiers.

- [ ] Add settings validation that graph checkpointing requires a writable configured volume and rejects an ephemeral production path.
- [ ] Add a persistence test: invoke, close saver, reopen saver, resume the same thread, and assert state revision is unchanged until committed.
- [ ] Configure one persistent checkpoint volume and health check; document single-instance constraint.
- [ ] Add tests for missing/corrupt checkpoint behavior and visible API error handling.
- [ ] Run `pytest -q tests/test_agent_graph.py tests/test_settings.py` from `web/api/` and verify no raw user ID appears in checkpoint paths or log fields.

### Task 4: Shadow, compare, and enable through feature flags

**Files:**
- Modify: `api/app/main.py`, `api/app/settings.py`
- Create: `api/evals/compare_graph_shadow.py`
- Test: `api/tests/test_api.py`, `api/tests/test_eval.py`

**Interfaces:** Shadow comparator emits only redacted outcome categories, graph version, and stable result hashes; it does not persist graph side effects.

- [ ] Add tests that shadow execution calls no mutation tool and emits no user text to telemetry.
- [ ] Run graph and current engine against the same fixed cases; produce a machine-readable diff by recommendation, citation IDs, and proposed actions.
- [ ] Require zero hard-constraint, source-citation, and action-authorization regressions before enabling the graph flag for staff.
- [ ] Add a one-step disable procedure and test that turning the flag off restores the existing route without database migration.
- [ ] Run full API, frontend, Agent Eval, and RAG Eval suites before staff enablement.
