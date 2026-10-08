.PHONY: help dev build test verify install clean screenshots check-origins
.PHONY: api-install api-test api-dev api-dev-bg wait-api check-api check-venv
.PHONY: db-up db-down migrate revision seed
.PHONY: check-dates check-programs-mirror check-programs-readers check-roadmap-mirror

WEB := web
SHOTS := docs/screenshots

# uv lives in the ignored .runtime-tools/ directory, together with the GitHub CLI.
# CURDIR keeps every recipe working when make is invoked with -C or from a subdirectory.
UV := $(CURDIR)/.runtime-tools/uv-aarch64-apple-darwin/uv

# uv refuses a home-directory cache in restricted environments, so cache beside uv,
# the same way npm uses .npm-cache instead of the system cache.
export UV_CACHE_DIR := $(CURDIR)/.runtime-tools/uv-cache

# With many targets it is hard to remember prerequisites, so list the ones annotated with ##.
# The pattern accepts any run of whitespace before `##` and after it, because the annotations are
# hand-written and an extra space used to be enough to hide a target from this list. The name column
# is wider than the longest target (`check-programs-mirror`), or its description runs into its name.
help:  ## List documented targets
	@grep -E '^[a-z][a-z0-9-]*:.*##[[:space:]]+[^[:space:]]' $(MAKEFILE_LIST) \
	  | sed 's/:.*##[[:space:]]*/\t/' | sort | awk -F'\t' '{printf "  %-24s %s\n", $$1, $$2}'

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

# `npm test` type-checks before it runs the tests, because `next build` skips `lib/*.test.ts` and
# would otherwise let a type error in a test file sit in the tree until someone ran tsc by hand.
test: check-dates check-programs-mirror check-programs-readers check-roadmap-mirror api-test  ## Run the frontend type-check and unit tests, plus the backend tests
	cd $(WEB) && npm test

verify: check-venv build test screenshots  ## Verify: build, unit tests and the end-to-end walkthrough

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

# The mirror guard binds the constants to the seed; this one binds the pages to the served row. The
# walkthrough's M2d check compares the page against the server's own answer, and the two catalogues
# agree on all six seeded programs, so restoring a `PROGRAMS.find(...)` in a view kept it green. This
# is the cheap, deterministic half: it walks the import graph out of the App Router's entry points and
# fails if web/lib/programs.ts is reachable from any of them, however many hops away. A grep over
# web/components and web/app was bypassable one re-export away — a lookup in web/lib kept it green.
check-programs-readers:  ## Fail if a page can reach web/lib/programs.ts through the import graph
	node scripts/check-no-programs-import.cjs

# The same two-part binding as the catalogue: without a database dump this compares
# web/lib/roadmap.ts against the committed snapshot, and api/tests/test_seed_roadmap.py compares the
# seeded rows against the same snapshot. The visa phase is excluded, because it is authored in the
# seed and has no counterpart in the TypeScript.
check-roadmap-mirror:  ## Fail if the seeded roadmap stops mirroring web/lib/roadmap.ts
	node scripts/verify-roadmap-mirror.cjs

check-origins:  ## Assert the dev server is interactive from every allowed origin (needs make dev running)
	node scripts/dev-origin-check.cjs

clean:  ## Remove build output
	rm -rf $(WEB)/.next $(WEB)/.next-build $(WEB)/node_modules
	@echo "Cleaned. Run make install again to restore node_modules."

api-install:  ## Create the backend venv (if missing) and install the backend dependencies
	@test -x "$(UV)" || { echo "uv not found at $(UV); download it into .runtime-tools/ first" >&2; exit 1; }
	@test -x api/.venv/bin/python || "$(UV)" venv --python 3.12 api/.venv
	cd api && "$(UV)" pip install --python .venv/bin/python -e ".[test]"

# `test` runs this through `api-test`, and `verify` runs `build` before `test`. A checkout without the
# backend venv used to spend a whole Next build before reaching the guard, so it is its own target and
# `verify` names it first: a precondition is worth having only when it fires before the expensive work.
check-venv:  ## Fail unless the backend virtualenv exists
	@test -x api/.venv/bin/python || { echo "api/.venv is missing; run make api-install first" >&2; exit 1; }

api-test: check-venv  ## Run the backend tests in the project-local venv
	cd api && .venv/bin/pytest -q

api-dev:  ## Start the backend dev server on :8000
	cd api && .venv/bin/uvicorn app.main:app --reload --port 8000

db-up:  ## Start the database container
	docker compose up -d db

db-down:  ## Stop the database container
	docker compose down

migrate:  ## Apply the database migrations
	cd api && .venv/bin/alembic upgrade head

revision:  ## Generate a new migration, usage: make revision m="add profiles"
	cd api && .venv/bin/alembic revision --autogenerate -m "$(m)"

seed:  ## Seed the placeholder program catalogue
	cd api && .venv/bin/python seed_cli.py
