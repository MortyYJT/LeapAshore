# Stage 1 skeleton verification

Date: 2026-10-05 (Australia/Melbourne)
Scope: `web/` front end skeleton (tasks T1–T3)
Verified by: parent agent, executed on the local machine

Status is reported per dimension. Anything not exercised is marked as not verified.

## 1. Build

Command: `make build` (that is `cd web && npm run build`)

Result: **passed**

```
▲ Next.js 16.2.11 (Turbopack)
✓ Compiled successfully in 1178ms
  Running TypeScript ...
  Finished TypeScript in 778ms
✓ Generating static pages (3/3) in 122ms

Route (app)
┌ ○ /
└ ○ /_not-found
```

TypeScript runs in strict mode (`strict: true`); there are no type errors.

## 2. End-to-end walkthrough

Command: `make screenshots` (that is `node scripts/e2e-walkthrough.cjs`)

A real Chromium instance borrowed from a sibling checkout drives the whole flow: complete the ten
onboarding steps, generate a plan, pick a portfolio, confirm it, open the flow view, select a node,
tick a material, visit all four tabs, then reload the page.

Result: **all 16 screenshots produced** in `docs/screenshots/`.

## 3. Runtime errors

Browser `console` errors plus uncaught `pageerror` events:

```
=== JS 错误 ===
无
```

Zero errors.

## 4. Persistence

After a page reload the flow view was still displayed instead of the onboarding:

```
刷新后仍在主流程（localStorage 生效）: true
```

## 5. Feature checkpoints

| Feature | Evidence |
|---|---|
| Green progress bar and `x/y` counter | `01-step1-education.png` shows `1/10`; `03-step3-school-detected.png` shows `3/10` |
| Automatic school-tier detection | Typing 北京邮电 resolves to 北京邮电大学 · 211, matched by full name |
| Generation transition | `07-generating.png` shows the four-stage sequence |
| Reach / steady / safe portfolio | `08-portfolio.png` shows tier tags, gap status, reasons, risks, and source links |
| Unverified-data notice | Yellow banner at the top of `08-portfolio.png` |
| Roadmap nodes | `10-flow.png` shows six phases with status, suggested date, and material counts |
| Node detail panel | Right side of `10-flow.png` shows the material checklist, suggested date, and official deadline marked as pending verification |
| Material checkboxes drive phase status | `12-material-checked.png` |
| Four-tab navigation | `13-home.png`, `14-profile.png`, `15-advisor.png` |

## 6. Interface exception

Per AGENTS.md, pages and styles are accepted from real browser output, so no TDD or code review was
applied to the interface. The screenshots and `console` output above are the acceptance record.

## 6.1 CSS cascade bug found through Context7 (fixed and re-verified)

Following the rule to check library APIs against official documentation, Tailwind v4 guidance was
retrieved from Context7. Two practices disagreed with this repository:

| Item | Documented practice | Before the fix | Outcome |
|---|---|---|---|
| Where design tokens live | `@theme { --color-*: ... }` | `:root { --brand: ... }` | Migrated; tokens now also generate utilities |
| Where custom component classes live | `@layer components` | No layer | **Unlayered `.card { background: #fff }` overrode `bg-*` utilities**; fixed |

Reproducible evidence: before the fix, the normalisation card in `docs/screenshots/04-step5-gpa.png`
rendered white even though it requested a soft grey background. After migrating to the documented
structure and restarting the dev server with a cleared `.next` directory, the same screenshot renders
correctly.

The fix also exposed a latent design defect: that card used the same colour as the page background, so
once the cascade was correct it became invisible. The redundant background utility was removed and the
card now takes the default white surface.

After the fix: `make build` passes, `make screenshots` passes, and the browser error count is still 0.

## 7. Local run

- Development server: `next dev` served `http://localhost:3000` and answered requests with HTTP 200.
- Build output: `.next/` was produced.

## 8. Not verified / not implemented

| Item | Status |
|---|---|
| FastAPI backend | **Not started**; does not exist |
| Server-side persistence | **Not implemented**; state lives in `localStorage` only |
| Agent or any model call | **Not implemented**; the advisor tab is a placeholder |
| Official deadlines | **All marked pending verification**; no real data |
| Unit tests for `lib/` | **Not written** (task T4, known gap) |
| CI | Workflow committed; **never executed on GitHub** |
| Deployment or containers | **Not verified** |
| Mobile devices | Not tested on real hardware; only responsive layout |
| Material templates per degree or field | **Not differentiated yet** (task T5) |

## 9. Relationship to the previous implementation

The previous project at `留学agent/web` was not modified. It served only as a read-only reference and
as the source of the Playwright installation.

No code was reused. The skeleton was written against the new product shape; only the domain object
names and the intent behind official-source governance were carried over.
