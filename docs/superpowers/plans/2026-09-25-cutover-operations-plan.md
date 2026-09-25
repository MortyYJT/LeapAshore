# Cutover and Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operate the expanded Agent stack with verified recovery, bounded resource use, gradual traffic exposure, and a tested return to the current implementation.

**Architecture:** Deploy new services dark, restore-test every persistent store, run shadow comparisons, then enable one feature at a time for staff and limited Beta. Feature flags and the current PostgreSQL/deterministic paths remain available through every release.

**Tech Stack:** Docker Compose, existing production FastAPI/Next.js deployment, PostgreSQL/Alembic, MySQL, Milvus/etcd/MinIO, Langfuse/PostgreSQL/ClickHouse/Redis/MinIO, SQLite checkpoint, Prometheus, Sentry, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-25-mewhelp-full-stack-rebuild-design.md`

## Global Constraints

- Never apply destructive migration or production release without a tested backup and reviewed rollback point.
- Use non-default secrets; bind admin and data ports to private interfaces.
- Keep all services feature-disabled until readiness, privacy, restore, and evaluation gates pass.
- Release one capability at a time and retain an immediate flag-based rollback.
- Do not claim production SLO or capacity until measured under representative load.

## Review Focus

- Restart/redeploy with pending outbox events; assert projection catches up without duplicates.
- Restore each database and object/index/checkpoint store into a new disposable environment and compare hashes/counts.
- Expire or revoke a source and verify it disappears from all retrieval paths within the documented window.
- Disable each upstream/service during a live request and verify bounded degradation without hidden provider switch.
- Rollback while new data exists and confirm old code ignores additive projection data safely.

---

### Task 1: Add production configuration and preflight checks

**Files:**
- Modify: `compose.production.yaml`, `api/app/settings.py`
- Create: `deploy/preflight-agent-stack.sh`
- Modify: `.env.production.example`, `docs/BETA_LAUNCH_RUNBOOK.md`
- Create: `api/tests/test_agent_stack_preflight.py`

**Interfaces:** Preflight returns named pass/fail checks for feature flags, service readiness, secrets, disk, backup freshness, index version, and classifier artifact. It must not print credential values.

- [ ] Add startup validation rejecting sample/default MySQL, Milvus, MCP, and Langfuse credentials in production.
- [ ] Add settings tests for each missing service, invalid public bind, unsupported feature combination, and redacted configuration output.
- [ ] Add health checks with bounded timeouts and readiness dependencies; optional services remain optional while their feature flags are off.
- [ ] Run preflight against a disposable compose stack and verify each deliberately invalid configuration fails with a safe message.

### Task 2: Implement backup and restore evidence for every store

**Files:**
- Create: `deploy/mysql-backup.sh`, `deploy/mysql-restore-smoke.sh`
- Create: `deploy/milvus-backup.sh`, `deploy/milvus-restore-smoke.sh`
- Create: `deploy/checkpoint-backup.sh`, `deploy/checkpoint-restore-smoke.sh`
- Modify: `deploy/backup.sh`, `deploy/restore-smoke.sh`, `docs/BETA_LAUNCH_RUNBOOK.md`

**Interfaces:** Each restore smoke requires an explicit disposable-environment confirmation flag, restores into a newly named empty target, and emits artifact checksum plus row/index/checkpoint integrity summary.

- [ ] Add tests that scripts refuse production-looking targets and refuse to overwrite a non-empty target.
- [ ] Back up PostgreSQL, MySQL, Milvus metadata/object dependencies, Langfuse stores, and checkpoint volume with encrypted-at-rest storage policy.
- [ ] Restore each artifact into a new ephemeral namespace; verify PostgreSQL revisions, MySQL projection revisions, Milvus source/index version coverage, and checkpoint thread/version metadata.
- [ ] Run deletion/retention checks for a test subject and ensure configured live stores remove it while backup retention is documented.
- [ ] Record actual recovery time and any manual step; label it measured only for this test environment.

### Task 3: Add shadow and staged release controls

**Files:**
- Modify: `api/app/settings.py`, `api/app/main.py`
- Modify: `compose.production.yaml`, `docs/BETA_LAUNCH_RUNBOOK.md`
- Create: `api/tests/test_agent_feature_flags.py`
- Modify: `e2e/happy-path.spec.ts`

**Interfaces:** Independent flags: graph runtime, MySQL projection writes/reads, Milvus build/shadow/read, MCP, Langfuse, classifier shadow/route. Dependencies are validated at startup; user-visible outputs record a safe workflow version.

- [ ] Add tests for every valid/invalid flag dependency and prove disabling each flag restores the prior route.
- [ ] Keep MySQL and Milvus in write-shadow mode first; compare IDs/hashes/ranking but never change user-visible results.
- [ ] Add staff-only rollout targeting through an existing trusted server-side configuration; do not accept role/flag claims from browser input.
- [ ] Add a runbook sequence for shadow → staff → limited Beta → broader release, with go/no-go and rollback metrics for each stage.
- [ ] Run browser E2E through current flow and graph shadow flow with each optional service independently disabled.

### Task 4: Load, failure, and rollback rehearsal

**Files:**
- Create: `api/evals/load_agent_stack.py`
- Create: `api/evals/failure_matrix.py`
- Modify: `docs/OBSERVABILITY.md`, `docs/BETA_LAUNCH_RUNBOOK.md`
- Create: `docs/superpowers/plans/evidence/2026-09-25-cutover-readiness.md`

**Interfaces:** Load runner emits fixed labels and aggregate timings only. Failure matrix documents injected fault, expected fallback, actual result, and release-blocking status.

- [ ] Add a reproducible load profile based on measured Beta request volume; do not invent target throughput.
- [ ] Inject MySQL, Milvus, embedding, reranker, MCP, Langfuse, checkpoint, and chat-provider outages one at a time.
- [ ] Exercise consent revocation, duplicate request replay, stale revision, source rollback, and privacy deletion during gray traffic.
- [ ] Rehearse full rollback to old graph/provider/retrieval paths while retaining additive data for later reconciliation.
- [ ] Complete readiness record with passed, failed, skipped, and unverified items; block cutover on unresolved data loss, privacy, hard-constraint, citation, or duplicate-action regression.
