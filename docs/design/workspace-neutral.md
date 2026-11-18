# Workspace visual refactor

The supplied dashboard screenshot is the visual source of truth. The application retains Next.js, its API proxy, authentication provider, profile and roadmap hooks, school catalogue and application storage.

## Shared layout

- A 64 px header and a 20% sidebar (190–260 px), with five primary destinations and settings at the bottom.
- At widths up to 700 px the sidebar becomes a toggleable drawer with a dismissible backdrop.
- Dashboard: breadcrumb, welcome, two metric cards, current-stage progress, and directly editable current-stage tasks.
- The stage counter and progress indicate the current stage's position. Pending count covers the current stage. Neither is hardcoded.
- Task updates use `useRoadmap.tick`, including existing optimistic updates, server persistence and failure rollback. Unsaved server rows cannot be toggled.
- Portfolio rows are ordered by 冲 / 稳 / 保 with compact group headings; all draft edits and confirmation behavior remain.

## Theme

Neutral light and dark semantic variables come from https://ui.shadcn.com/docs/theming . Legacy component variables alias these semantic values. Green `#4B927F` is reserved for progress. Existing appearance settings retain light, dark and system modes; the header shortcut uses the same persisted preference. Decorative surfaces and configurable brand colors are removed.

## Verification

Run `npm --prefix web test`, `make build`, and `node scripts/walkthrough.cjs` with the frontend and authenticated local API running. The walkthrough creates temporary accounts and removes them, and substitutes the paid AI response while checking the real authenticated chat request. It covers catalogue search, portfolio persistence, task persistence, material upload, permissions, theme persistence and desktop/mobile layout. The overview also has a refresh-after-tick check.

The homepage is now the overview, so previous landing-page and automatic-roadmap-redirect assertions have been updated to the new navigation behavior. No production deployment is performed by this refactor.
