.PHONY: help dev build test verify install clean screenshots check-origins
.PHONY: api-install api-test api-dev

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

dev:  ## Start the frontend dev server on :3000
	cd $(WEB) && npm run dev

build:  ## Type-check and build into .next-build so a running dev server is untouched
	cd $(WEB) && NEXT_DIST_DIR=.next-build npm run build

test: api-test  ## Run the frontend and backend unit tests
	cd $(WEB) && npm test

verify: build test screenshots  ## Verify: build, unit tests and the end-to-end walkthrough

screenshots:  ## Drive the full flow in a real browser, writing screenshots to docs/screenshots/
	node scripts/e2e-walkthrough.cjs

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
	cd api && .venv/bin/pytest -q

api-dev:  ## Start the backend dev server on :8000
	cd api && .venv/bin/uvicorn app.main:app --reload --port 8000
