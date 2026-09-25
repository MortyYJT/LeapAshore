# OfferPilot Runtime and Rollback Inventory — 2026-09-25

## Existing local Compose topology

| Service | Container port / host binding | Persistent data | Readiness |
|---|---|---|---|
| `postgres` | 5432, internal compose network only | `postgres_data` | `pg_isready` against OfferPilot DB |
| `api` | 8000, internal compose network only | no local service volume; DB in Postgres | `/health/readiness`, waits for Postgres healthy |
| `web` | 3000, internal compose network only | no local service volume | waits for API healthy |
| `gateway` / Caddy | development host `${PORT:-8080}:80`, `${HTTPS_PORT:-8443}:443`; production `80:80`, `443:443` | `caddy_data`, `caddy_config`; Caddyfile bind-mounted read-only | waits for web and API containers |
| `ollama` (offline profile) | 11434, internal compose network only | `ollama_data` | `ollama list` |
| `model-init` (offline profile) | no listening port | none | one-shot model check/download, retries five times then leaves API deterministic fallback available |
| `backup` (production compose overlay) | no listening port | `postgres_backups` | recent dump file within 25 hours; PostgreSQL must be healthy |
| `mailpit` (optional `compose.mailpit.yaml`) | SMTP 1025 internal; UI `127.0.0.1:${MAILPIT_UI_PORT:-8025}:8025` | ephemeral unless external volume is added | Compose health dependency |

The current Compose configuration binds no PostgreSQL, API, or web host port directly; access is through the gateway. Compose service ports 3000, 5432, 8000, and 11434 are internal to its network. The only explicit local host ports in the current files are gateway 8080/8443 (or 80/443 in production) and optional Mailpit UI 8025. The worktree environment has Docker Compose CLI 5.3.0, but the Docker daemon is unavailable; live service health and port occupancy were not measured.

## Existing production persistence and credentials (names only)

- Persistent volumes: `postgres_data`, `postgres_backups`, `caddy_data`, and `caddy_config`; `ollama_data` for the opt-in offline profile.
- PostgreSQL backup: custom-format `pg_dump` to an `.incomplete` path then atomic rename; configured default retention is 7 days and interval 24 hours. The production runbook says a checksum/manifest restore smoke runs in CI. This local session did not run against a live DB.
- Existing sensitive/config values by variable name: `POSTGRES_PASSWORD`, `DATABASE_URL`, `DEEPSEEK_API_KEY`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SENTRY_DSN`, `METRICS_BEARER_TOKEN`, `ADMIN_EMAILS`, `DOMAIN`, `CORS_ORIGINS`, and provider/model config (`LLM_PROVIDER`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`). No values are copied into this inventory.
- New stack variables do not exist in the current environment template. The implementation plans must add distinct MySQL, Milvus, MCP, Langfuse, embedding, reranker, and classifier configuration names in the relevant phase; production defaults must not reuse example credentials.
- Current compose files declare no CPU or memory reservations/limits. No minimum host RAM, disk, expected throughput, or production latency was established here. Resource capacity is unmeasured.

## New stack port and volume reservations for planning

Keep new stateful services on private Compose networks. Proposed internal endpoints are MySQL 3306, Milvus 19530/9091, etcd 2379, Milvus MinIO 9000/9001, MCP on a private configured port, and Langfuse web on a private configured port. These are reservations to be checked against deployment host policy, not confirmed available ports. Do not bind etcd, either MinIO, ClickHouse, Redis, MySQL, or Milvus to public interfaces. Langfuse MinIO and Milvus MinIO use separate services and volumes. The primary product gateway continues to own public 80/443.

Planned new named volumes: MySQL Agent DB; Milvus etcd metadata, object storage, and data; independent Langfuse PostgreSQL, ClickHouse, Redis, and MinIO; SQLite graph checkpoint. Names and backup methods are defined by the focused plans before any production deployment. No new service is running in this baseline.

## Rollback sequence

1. Disable online feature flags for classifier routing, MCP, hybrid retrieval, Langfuse callbacks, MySQL projection reads, and LangGraph advisor output. Keep graph/MySQL/Milvus/MCP services and volumes intact for diagnosis; no volume deletion or schema downgrade.
2. Route user-visible advisor and knowledge traffic through the existing FastAPI deterministic/consented-provider path and current BM25 retriever. Confirm consent, citation, CAS, idempotency, and SSE checks remain active.
3. Stop only the new projector/indexer/job consumers after preserving unacknowledged PostgreSQL outbox rows. Do not discard pending events; resume/reconcile them when the feature is re-enabled.
4. Verify APIs read canonical PostgreSQL data and inspect fixed Eval, refusal, citation, duplicate-action, error-rate, and latency results. Keep additive MySQL/Milvus/checkpoint data for later comparison.
5. If code rollback is needed, deploy the prior application image/commit while additive schema and volumes remain. Do not reverse or delete PostgreSQL migrations until an independently reviewed migration proves it is safe.
6. Re-enable one flag only after the relevant focused-plan exit gate and restore/reconciliation evidence pass again.

## Capacity and evidence limits

- Local baseline tests and Evals pass as recorded in `2026-09-25-current-baseline.md`; they are not representative load tests.
- Docker daemon, live PostgreSQL, per-service health, network port availability, storage growth, LangGraph checkpoint recovery, and production load are unverified.
- Milvus/etcd/MinIO and the Langfuse web/worker/PostgreSQL/ClickHouse/Redis/MinIO stack increase memory, disk, backup, and upgrade requirements. Do not state a minimum host size until a disposable stack is measured and a representative load profile is run.
- Production secret rotation and retention values remain governed by deployment policy; this plan does not provision, display, or change them.
