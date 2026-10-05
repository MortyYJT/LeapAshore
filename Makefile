.PHONY: help dev build verify install clean screenshots

WEB := web
SHOTS := docs/screenshots

# With many targets it is hard to remember prerequisites, so list the ones annotated with ##.
help:  ## List documented targets
	@grep -E '^[a-z][a-z0-9-]*:.*?## ' $(MAKEFILE_LIST) \
	  | sed 's/:.*## /\t/' | sort | awk -F'\t' '{printf "  %-16s %s\n", $$1, $$2}'

install:  ## Install frontend dependencies using a repository-local npm cache
	cd $(WEB) && npm install --no-audit --no-fund --cache ../.npm-cache

dev:  ## Start the frontend dev server on :3000
	cd $(WEB) && npm run dev

build:  ## Type-check and build
	cd $(WEB) && npm run build

verify: build screenshots  ## Verify: build plus the end-to-end screenshot walkthrough

screenshots:  ## Drive the full flow in a real browser, writing screenshots to docs/screenshots/
	node scripts/e2e-walkthrough.cjs

clean:  ## Remove build output
	rm -rf $(WEB)/.next $(WEB)/node_modules
	@echo "Cleaned. Run make install again to restore node_modules."
