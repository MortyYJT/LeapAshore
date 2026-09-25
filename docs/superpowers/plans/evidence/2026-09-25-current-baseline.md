# OfferPilot Baseline Evidence — 2026-09-25

## Checkout and environment

- Isolated worktree: `/tmp/offerpilot-mewhelp-fullstack`
- Starting commit: `9795a3de820a96d1068f882fce8088a1e989c090`
- Branch: `feature/offerpilot-mewhelp-fullstack`
- Frontend runtime: Node `v24.19.0`, pnpm `11.19.0`
- API runtime: Python `3.12.14`; API venv installed from `api/requirements-dev.txt`
- Resolved API versions: FastAPI `0.141.1`, Pydantic `2.13.5`, httpx `0.28.1`, pytest `9.1.1`, Sentry SDK `2.70.0`
- Docker Compose CLI: `v5.3.0`; Docker daemon unavailable (`docker info` exited non-zero)
- `uv` is not installed. This baseline uses the API requirements file in a Python 3.12 virtual environment; it is not a uv-locked environment.
- `DATABASE_URL` is unset; `psql` and `pg_dump` are not installed.
- No `AGENTS.md` files were found in the repository.

## Results

| Check | Result | Evidence / qualification |
|---|---|---|
| `pnpm install --frozen-lockfile` | passed | Lockfile accepted; 498 packages installed in the isolated worktree. |
| `pnpm test` | passed | Vinext build completed; Node runner reported 31 passed, 0 failed, 0 skipped. Build emitted the existing static-analysis notice that some routes cannot be classified. The restore-script unit tests passed, but they use test fixtures and do not prove a live database restore. |
| `pnpm run lint` | passed | Exit code 0; no lint output. |
| `CI=1 E2E_PYTHON=api/.venv/bin/python pnpm run test:e2e` | passed | Playwright reported 8 passed in 23.9 seconds. Dev servers were started only on `127.0.0.1` ports 8100 and 3100. |
| `pytest -q` from `api/` | passed with skips | 107 passed, 5 skipped, 1 Starlette/httpx deprecation warning. All 5 skips are the PostgreSQL integration tests in `api/tests/test_postgres_store.py`, guarded by `DATABASE_URL`. |
| `python -m evals.run_eval` from `api/` | passed | 10 cases; hard-constraint accuracy 1.0, missing-information accuracy 1.0, citation coverage 1.0, tool success 1.0. |
| `python -m evals.run_rag_eval` from `api/` | passed | 12 retrieval + 5 no-answer cases; top-1 program/section accuracy, Recall@3, citation coverage, and no-answer rejection accuracy all 1.0. |
| `deploy/restore-smoke.sh` against a disposable PostgreSQL DB | skipped / unverified | No Docker daemon, `DATABASE_URL`, `psql`, or `pg_dump`; no explicitly provisioned disposable database was available. No restore command was run. |

## Invocation correction

An initial `pytest -q` invocation from the repository root failed collection because the API package is configured relative to `api/`. The documented command was rerun from `api/` and produced the 107-pass / 5-skip result above. This initial path error is not a product test failure.

## Baseline limits

- This is an isolated local test run, not production-like capacity or latency evidence.
- PostgreSQL transactional/concurrency and restore behavior remain unverified in this environment.
- The Node build warning and API deprecation warning predate implementation; they are recorded for comparison.
