# Baseline and Runtime Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish reproducible baselines, data ownership, environment boundaries, and rollback evidence before adding runtime services.

**Architecture:** Inventory current FastAPI, Store, PostgreSQL migrations, advisor streaming, RAG, consent, telemetry, and deployment. Record test/eval outputs and define versioned event/projection contracts for the new Agent data plane without migrating production data.

**Tech Stack:** FastAPI, pytest, Node Test Runner, PostgreSQL, Alembic, Docker Compose, current Agent/RAG Eval scripts.

**Spec:** `docs/superpowers/specs/2026-09-25-mewhelp-full-stack-rebuild-design.md`

## Global Constraints

- Keep PostgreSQL authoritative for users, profiles, program facts, and source review.
- Do not expose or copy production data into local evaluation fixtures.
- Record every skipped/unavailable check as skipped; do not count it as passed.
- Preserve the existing runtime behavior and rollback path.

## Review Focus

- Verify each check used a clean, documented environment and exact command.
- Confirm the data ownership matrix identifies create, update, delete, replay, and retention behavior.
- Confirm production-only checks are explicitly listed as unverified when no safe production access exists.
- Confirm budgets and resource requirements are measured or labeled as estimates.
- Confirm the rollback plan does not require destructive schema changes.

---

### Task 1: Capture current runtime and evaluation baseline

**Files:**
- Create: `docs/superpowers/plans/evidence/2026-09-25-current-baseline.md`
- Read: `README.md`, `api/pyproject.toml`, `docs/RAG_ARCHITECTURE.md`, `docs/OBSERVABILITY.md`, `docs/BETA_LAUNCH_RUNBOOK.md`
- Test: `api/tests/`, `api/evals/`, `tests/`, `e2e/`

**Interfaces:** Consumes existing app commands and fixtures. Produces a dated evidence record used by every later plan.

- [ ] Run `pnpm test` and `pnpm run lint` from `web/`; record exit status and skipped checks.
- [ ] Run `pnpm run test:e2e` from `web/` in the supported local browser environment; record whether a browser/runtime was available.
- [ ] Run `pytest -q` from `web/api/`; record PostgreSQL integration skips separately.
- [ ] Run `python -m evals.run_eval` and `python -m evals.run_rag_eval` from `web/api/`; save exact JSON output in the baseline record.
- [ ] Run `deploy/restore-smoke.sh` only against a disposable PostgreSQL test database with `RESTORE_SMOKE_CONFIRM_EPHEMERAL=1`; record its checksum and table comparison result.
- [ ] Review the resulting baseline record and verify it contains command, environment, exit code, results, and skipped/unverified status for each check.

### Task 2: Define data ownership and migration contracts

**Files:**
- Create: `docs/superpowers/plans/evidence/2026-09-25-data-ownership.md`
- Create: `docs/superpowers/plans/evidence/2026-09-25-event-contracts.md`
- Read: `api/app/store.py`, `api/app/source_governance.py`, `api/app/models.py`, `api/app/main.py`

**Interfaces:** PostgreSQL owns profile and published-source revisions. Future MySQL projections consume versioned Agent events; Milvus consumes published-source outbox events; LangGraph checkpoints remain a separate resumable-state store.

- [ ] List each entity with owner, key, write path, readers, deletion path, retention, and recovery source.
- [ ] Define event envelope fields: `event_id`, `event_type`, `schema_version`, `aggregate_id`, `source_revision`, `occurred_at`, and redacted payload.
- [ ] Define deterministic projection idempotency key as `(event_id, projection_name)` and stale-event rule as `source_revision <= applied_revision`.
- [ ] Define privacy deletion propagation across PostgreSQL, MySQL, checkpoint storage, Langfuse, and backups.
- [ ] Review both artifacts against the approved specification and resolve any conflicting ownership before enabling a new store.

### Task 3: Freeze deployment and rollback boundary

**Files:**
- Create: `docs/superpowers/plans/evidence/2026-09-25-runtime-inventory.md`
- Read: `compose.yaml`, `compose.production.yaml`, `api/Dockerfile`, `Dockerfile`, `deploy/backup.sh`, `deploy/restore-smoke.sh`

**Interfaces:** Produces the service/resource inventory and the rollback sequence consumed by the operations plan.

- [ ] Record current service names, exposed ports, persistent volumes, health checks, and secret names without secret values.
- [ ] Record which components share a host and which existing ports/volumes are already allocated.
- [ ] Write a rollback sequence that disables new graph, MySQL, Milvus, MCP, and Langfuse flags without deleting their data.
- [ ] Review the inventory against the minimum test and production resource estimate; mark unmeasured capacity explicitly.
