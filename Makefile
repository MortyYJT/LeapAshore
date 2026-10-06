.PHONY: help dev build test verify install clean screenshots check-origins
.PHONY: api-install api-test api-dev api-dev-bg wait-api check-api
.PHONY: db-up db-down migrate revision seed
.PHONY: check-dates check-programs-mirror

WEB := web
SHOTS := docs/screenshots

# uv lives in the ignored .runtime-tools/ directory, together with the GitHub CLI.
# CURDIR keeps every recipe working when make is invoked with -C or from a subdirectory.
UV := $(CURDIR)/.runtime-tools/uv-aarch64-apple-darwin/uv

# uv refuses a home-directory cache in restricted environments, so cache beside uv,
# the same way npm uses .npm-cache instead of the system cache.
export UV_CACHE_DIR := $(CURDIR)/.runtime-tools/uv-cache

# With many targets it is hard to remember prerequisites, so list the ones annotated with ##.
help:  ## List documented targets
	@grep -E '^[a-z][a-z0-9-]*:.*?## ' $(MAKEFILE_LIST) \
	  | sed 's/:.*## /\t/' | sort | awk -F'\t' '{printf "  %-16s %s\n", $$1, $$2}'

install: api-install  ## Install frontend and backend dependencies
	cd $(WEB) && npm install --no-audit --no-fund --cache ../.npm-cache

dev: db-up api-dev-bg  ## Start the database, the API on :8000 and the frontend dev server on :3000
	@trap 'kill 0' EXIT INT TERM; cd $(WEB) && npm run dev

# The browser now reads the applicant's profile from the API, so a dev server without a backend
# renders a page whose profile is permanently empty. Start it in the background, detached from this
# shell's job control, and wait for the health probe instead of assuming the port answers.
api-dev-bg:  ## Start the API in the background and wait until it answers
	@cd api && nohup .venv/bin/uvicorn app.main:app --port 8000 >/tmp/offerpilot-api.log 2>&1 &
	@$(MAKE) --no-print-directory wait-api

build:  ## Type-check and build into .next-build so a running dev server is untouched
	cd $(WEB) && NEXT_DIST_DIR=.next-build npm run build

test: check-dates check-programs-mirror api-test  ## Run the frontend and backend unit tests
	cd $(WEB) && npm test

verify: build test screenshots  ## Verify: build, unit tests and the end-to-end walkthrough

# The walkthrough asserts the API before opening the browser, so this target failed at the page
# rather than after a full run. Checking here too keeps `make verify` from spending a build and the
# whole unit suite before saying the backend was never up.
screenshots: check-api  ## Drive the full flow in a real browser, writing screenshots to docs/screenshots/
	node scripts/e2e-walkthrough.cjs

check-api:  ## Fail unless the API answers on :8000
	@curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:8000/api/health \
	  || { echo "后端未运行：http://127.0.0.1:8000/api/health 无响应。先运行 make dev（同时启动前后端）或 make api-dev。" >&2; exit 1; }

wait-api:  ## Wait for the API started by api-dev-bg to answer
	@for i in $$(seq 1 40); do \
	  curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:8000/api/health && break; \
	  test $$i -lt 40 || { echo "后端 20 秒内未启动，见 /tmp/offerpilot-api.log" >&2; exit 1; }; \
	  sleep 0.5; \
	done

check-dates:  ## Fail if a verification date is hardcoded in source or seed data
	node scripts/check-no-fake-dates.cjs

# Without a database dump this still compares web/lib/programs.ts against the committed snapshot, so
# the check runs even when the container is down. api/tests/test_seed.py compares the seeded rows
# against the same snapshot, which is what binds the tables to the frontend data.
check-programs-mirror:  ## Fail if the seeded catalogue stops mirroring web/lib/programs.ts
	node scripts/verify-programs-mirror.cjs

check-origins:  ## Assert the dev server is interactive from every allowed origin (needs make dev running)
	node scripts/dev-origin-check.cjs

clean:  ## Remove build output
	rm -rf $(WEB)/.next $(WEB)/.next-build $(WEB)/node_modules
	@echo "Cleaned. Run make install again to restore node_modules."

api-install:  ## Create the backend venv (if missing) and install the backend dependencies
	@test -x "$(UV)" || { echo "uv not found at $(UV); download it into .runtime-tools/ first" >&2; exit 1; }
	@test -x api/.venv/bin/python || "$(UV)" venv --python 3.12 api/.venv
	cd api && "$(UV)" pip install --python .venv/bin/python -e ".[test]"

api-test:  ## Run the backend tests in the project-local venv
	@test -x api/.venv/bin/python || { echo "api/.venv is missing; run make api-install first" >&2; exit 1; }
	cd api && .venv/bin/pytest -q

api-dev:  ## Start the backend dev server on :8000
	cd api && .venv/bin/uvicorn app.main:app --reload --port 8000

db-up: ## Start the database container
	docker compose up -d db

db-down: ## Stop the database container
	docker compose down

migrate: ## Apply the database migrations
	cd api && .venv/bin/alembic upgrade head

revision: ## Generate a new migration, usage: make revision m="add profiles"
	cd api && .venv/bin/alembic revision --autogenerate -m "$(m)"

seed: ## Seed the placeholder program catalogue
	cd api && .venv/bin/python seed_cli.py
