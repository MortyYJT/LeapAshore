## Progress checklist (a successor resumes from the first unticked box)

Branch `claude/auth-login`. Run backend tests with `cd api && .venv/bin/python -m pytest -q`.

## 0. Docs first

- [ ] 0.1 PRD: drop "不需要注册", list pages that need login, replace the assessment with the info step
- [ ] 0.2 This OpenSpec change validates (`openspec validate account-login`)

## 1. Backend: schema and config

- [ ] 1.1 Alembic revision: `accounts`, `auth_sessions`, `login_codes` (add-only)
- [ ] 1.2 Settings: `AUTH_ENABLED`, `APP_ENV`, `MAIL_BACKEND`, `SMTP_*`, `MAIL_FROM`, `TRUST_FORWARDED_FOR`, limits
- [ ] 1.3 Red/green: production guard refuses the log backend (startup check + backend refusal)

## 2. Backend: codes, sessions, login

- [ ] 2.1 Red/green: code send — 60 s resend, per-email and per-IP daily caps, new code invalidates old
- [ ] 2.2 Red/green: verify — expiry, single use, 5-attempt cut-off, concurrent guesses
- [ ] 2.3 Red/green: first login registers; concurrent first logins create one account
- [ ] 2.4 Red/green: sessions — cookie, `/me`, logout, expiry
- [ ] 2.5 Mail backends: `log` (log + `api/var/mail.log`) and `smtp` (smtplib, tested with a fake server)

## 3. Backend: subject resolution and isolation

- [ ] 3.1 `get_subject` / `get_optional_subject` honour the switch; every router uses them
- [ ] 3.2 Red/green: logged-out private routes 401 in login mode, public routes 200, roadmap `tasks: []`
- [ ] 3.3 Red/green: A cannot read or write B (profile, applications, documents, tasks, advisor tools)

## 4. Backend: merge, deletion, sweep

- [ ] 4.1 Red/green: new account claims the anonymous subject
- [ ] 4.2 Red/green: existing account merge rules (profile unit, portfolio, tasks, documents, events)
- [ ] 4.3 Red/green: account deletion removes every row and unreferenced blobs
- [ ] 4.4 Red/green: `python -m app.cleanup` 90-day sweep (+ expired sessions and old codes)
- [ ] 4.5 `last_seen_at` touched at most daily

## 5. Web

- [ ] 5.1 `lib/auth.ts` + tests; `AuthProvider`; login dialog (email → code → info step)
- [ ] 5.2 Gate actions: advisor send/confirm (resume original sentence), 加入选校, portfolio save, roadmap writes, 我的 edits
- [ ] 5.3 `/tiers` (moved from `/assess/result`) with 先补信息; remove `/assess`; redirects
- [ ] 5.4 `/me` editable profile + 退出登录 + 注销账号; header 登录 / account menu
- [ ] 5.5 `/privacy` draft page, linked from the dialog and the footer
- [ ] 5.6 Logged-out states for `/portfolio`, `/me`, `/tiers`, `/roadmap` (sample)
- [ ] 5.7 Update landing redirect (`proxy.ts`) to forward the session cookie

## 6. Verify and ship

- [ ] 6.1 Walkthrough: 未登录点发送 → 登录 → 信息页 → 回到顾问并发出原句; logout; account deletion
- [ ] 6.2 `make verify` green
- [ ] 6.3 Deploy config: compose passes `APP_ENV=production`, `TRUST_FORWARDED_FOR=true`; `.env.example` lists the new keys
- [ ] 6.4 TASKS.md, `note/decisions.md`, `note/handoff.md` (DNS records, switch steps, cron line)
- [ ] 6.5 PR, CI, fresh-context review, merge, deploy with login mode off (backup, migrate, read-only checks)
