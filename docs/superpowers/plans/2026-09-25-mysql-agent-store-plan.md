# MySQL Agent Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the literal MewHelp SQLAlchemy/MySQL stack for Agent-domain projections without weakening PostgreSQL ownership or replay safety.

**Architecture:** PostgreSQL writes an outbox event in the same transaction as the authoritative advisor/source change. A retryable projection worker applies versioned, idempotent events to MySQL. MySQL is queryable for Agent audit and review operations, but cannot update PostgreSQL business facts. AsyncSqliteSaver remains the initial LangGraph checkpoint store.

**Tech Stack:** SQLAlchemy asyncio, asyncmy, MySQL 8, a separate Alembic migration environment, FastAPI lifespan, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-mewhelp-full-stack-rebuild-design.md`

## Global Constraints

- PostgreSQL remains authoritative for user/profile/source-review state and advisor-thread commit semantics.
- MySQL events use stable IDs and source revisions; duplicate, stale, or reordered events cannot overwrite newer projections.
- No raw cloud credentials, trace payloads, or unredacted evaluation data enter projection metadata.
- MySQL is initially opt-in, disposable, and rebuildable from authoritative events.

## Review Focus

- Database commit succeeds but worker fails: event remains replayable.
- Worker retries after MySQL commit but before acknowledgement: no duplicate record or counter increment.
- Older source revision arrives after a newer revision: projection remains at the newer version.
- User/account deletion removes or anonymizes all MySQL projections according to the approved retention policy.
- MySQL unavailable: current PostgreSQL-backed user flow remains available and reports degraded Agent observability clearly.

---

### Task 1: Create MySQL service and schema foundation

**Files:**
- Create: `api/app/agent_store/__init__.py`
- Create: `api/app/agent_store/database.py`
- Create: `api/app/agent_store/models.py`
- Create: `api/app/agent_store/repository.py`
- Create: `api/alembic_agent.ini`
- Create: `api/alembic_agent/env.py`
- Create: `api/alembic_agent/versions/0001_agent_projection.py`
- Create: `api/tests/test_mysql_agent_store.py`
- Modify: `api/pyproject.toml`, `api/requirements.txt`, `compose.yaml`

**Interfaces:** `AgentStore.healthcheck()`, `AgentStore.apply_event(event)`, `AgentStore.get_projection(aggregate_id)`, and `AgentStore.delete_subject(subject_ref)` are async. Event shape comes from `docs/superpowers/plans/evidence/2026-09-25-event-contracts.md`.

- [ ] Add an integration test that inserts an event projection and reads it using a disposable MySQL database; skip only when `MYSQL_TEST_URL` is absent.
- [ ] Confirm the integration test is skipped locally without Docker and passes in the configured CI service.
- [ ] Add environment settings for URL, connect timeout, pool size, and feature flag; never log the URL password.
- [ ] Add MySQL 8 service, private network binding, named volume, and health check to development compose; use a distinct service/volume name from MewHelp.
- [ ] Add initial MySQL-only Alembic revision for projection cursor, event receipt, advisor audit, and review candidate metadata; do not copy account credentials.
- [ ] Run `cd api && pytest -q tests/test_mysql_agent_store.py tests/test_settings.py` and inspect logs for credential leakage.

### Task 2: Implement transactional PostgreSQL outbox

**Files:**
- Modify: `api/app/store.py`, `api/app/postgres_store.py`, `api/app/models.py`
- Create: `api/app/agent_store/events.py`
- Create: `api/tests/test_agent_outbox.py`
- Test: `api/tests/test_postgres_store.py`

**Interfaces:** `AgentProjectionEvent` is immutable and versioned. `PostgresStore.reserve_advisor_turn(...)` and `save_thread(...)` append an outbox event atomically with the existing commit. Memory/SQLite adapters expose equivalent test behavior but cannot claim production durability.

- [ ] Add tests that the advisor message/thread revision and corresponding outbox event either commit together or both roll back.
- [ ] Add a test that a rejected stale CAS writes no outbox event.
- [ ] Add the outbox table through Alembic without changing current Store response models.
- [ ] Add a claim/ack repository that uses a bounded lease, attempt count, and idempotent event ID.
- [ ] Run PostgreSQL Store integration tests with two connections and verify no duplicate outbox event for one request ID.

### Task 3: Build idempotent MySQL projector and reconciler

**Files:**
- Create: `api/app/agent_store/projector.py`
- Create: `api/app/agent_store/reconcile.py`
- Create: `api/tests/test_agent_projector.py`
- Modify: `api/app/settings.py`, `compose.yaml`

**Interfaces:** `project_batch(limit: int) -> ProjectionBatchResult`; `reconcile_projection() -> ReconciliationReport`. Result fields contain counts and error classes, never event bodies.

- [ ] Add tests for duplicate event, stale revision, out-of-order events, invalid schema version, and partial batch failure.
- [ ] Implement projector transaction: record event receipt, compare source revision, upsert projection, commit, then acknowledge PostgreSQL outbox.
- [ ] Implement reconciliation by comparing stable aggregate IDs, revisions, and payload hashes, not sensitive message content.
- [ ] Add a bounded CLI job entry point that can resume after process termination and cannot accept shell fragments.
- [ ] Run projector tests against MySQL and PostgreSQL disposable services; assert replay twice produces the same hash/count.

### Task 4: Shadow read, privacy deletion, and restore

**Files:**
- Modify: `api/app/main.py`, `api/app/agent_store/repository.py`, `api/app/store.py`
- Modify: `api/tests/test_api.py`, `api/tests/test_mysql_agent_store.py`
- Create: `deploy/mysql-backup.sh`, `deploy/mysql-restore-smoke.sh`

**Interfaces:** Existing user API remains PostgreSQL-backed. Internal shadow comparison returns match/mismatch only. Deletion handler propagates a stable opaque subject reference and records completion per projection.

- [ ] Add tests that shadow reads cannot change response content or call any mutation path.
- [ ] Add account deletion tests covering PostgreSQL, MySQL projection, outbox tombstone, and pending retry behavior.
- [ ] Add encrypted backup/restore commands for the MySQL service; test only on an explicitly named ephemeral database.
- [ ] Rebuild MySQL from PostgreSQL events and compare aggregate IDs/revisions/hashes; record count and mismatch totals.
- [ ] Enable MySQL audit reads only after zero unexplained reconciliation mismatches and successful restore smoke.
- [ ] Run `cd api && pytest -q`, PostgreSQL concurrency tests, MySQL integration tests, and the privacy deletion tests.
