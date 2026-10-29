## Context

Every user-owned table (`profiles`, `applications`, `roadmap_tasks`, `task_events`, `documents`) is keyed by
`client_id`, a uuid minted into the `leapashore_client` cookie by `app.deps.get_client_id`. The advisor scopes
its LangGraph thread and its tools by the same id. Uploaded files are content-addressed under
`settings.document_storage_root` (one blob per SHA-256, shared by every version that has those bytes).
Production is a single server: Caddy terminates TLS and proxies `/api/*` straight to the API container.
Redis and Celery are approved but arrive in P1, so this change must not depend on them.

## Goals / Non-Goals

**Goals:** a real identity with a small attack surface; no change to how data rows are keyed; deploying the
code must be safe before mail is configured; anonymous data is not lost at first login.

**Non-Goals:** passwords, OAuth, multiple emails per account, changing the email of an account, admin roles
(P2 adds a role column), persisting advisor conversations (P1), Redis-based rate limiting (next P0 item).

## Decisions

### D1. An account owns exactly one data subject

`accounts(id, email UNIQUE, client_id UNIQUE → clients.id ON DELETE CASCADE, created_at, last_login_at)`.
The data tables keep their `client_id`; a logged-in request simply resolves to the account's client id. This
keeps every query, the advisor tools and the existing isolation tests unchanged, and it makes deletion one
`DELETE FROM clients` (the cascade already reaches every owned row, and now the account and its sessions).
*Alternative rejected:* an `account_id` column on every table — a rewrite of every query and a data migration
for nothing the subject indirection cannot already express.

### D2. Login mode is a switch; production stays anonymous until mail works

- `AUTH_ENABLED` (default `false` in code). The Makefile's `api-dev-bg` sets it to `true`, so local runs and
  the walkthrough exercise login mode; the existing suite keeps testing anonymous mode, and the auth tests
  turn the switch on per test.
- `APP_ENV` (`development` | `production`); production compose sets `production`.
- `MAIL_BACKEND` (`log` | `smtp`, default `log`). `log` writes the code to the application log and to
  `api/var/mail.log` (gitignored, local only), which is how the walkthrough reads it.
- **Guard**: at startup, `APP_ENV=production` with `AUTH_ENABLED=true` requires `MAIL_BACKEND=smtp` and every
  `SMTP_*` value, or the process exits with the reason. The `log` backend itself also refuses to send when
  `APP_ENV=production` (defence in depth). Deploying this change with `AUTH_ENABLED` unset is therefore a
  no-op for users.
- With the switch off, `/api/auth/code`, `/verify`, `/logout` and `DELETE /account` answer 404 `登录未开启`,
  and `GET /api/auth/me` says `authEnabled: false`, so the interface hides every login control.

### D3. Codes

- 6 digits from `secrets.randbelow`, stored as `sha256(salt || code)` with a per-row random salt; the plain
  code exists only in the mail. (A 6-digit hash can be brute-forced offline; the 10-minute life is what
  bounds that, and a database leak already exposes the data the code protects.)
- `login_codes(id, email, code_hash, salt, ip, created_at, expires_at, attempts, consumed_at, invalidated_at)`.
- Send (`POST /api/auth/code`): under `pg_advisory_xact_lock(hashtext(email))` so two concurrent sends for
  one email are serialised; refuse with 429 + `retryAfter` when the newest code for the email is younger than
  60 s, when the email has `AUTH_CODES_PER_EMAIL_PER_DAY` (10) codes in the last 24 h, or the IP has
  `AUTH_CODES_PER_IP_PER_DAY` (30). A new code invalidates every older live code of that email, so only one
  code can be guessed at a time.
- Verify (`POST /api/auth/verify`): read the newest live code `FOR UPDATE` (serialises concurrent guesses);
  none, expired, consumed or invalidated → 400 `code_expired`. Wrong → `attempts += 1`; at 5 the code is
  invalidated and the answer is 400 `too_many_attempts`, else 400 `wrong_code` with `remaining`. Right → set
  `consumed_at` in the same transaction that creates the session. Bound on guessing one mailbox: 5 guesses ×
  10 codes a day = 50 of 10⁶.
- Email is trimmed and lower-cased, at most 254 characters, one `@`, a dot in the domain.

### D4. Sessions

`auth_sessions(token_hash PK, account_id → accounts ON DELETE CASCADE, created_at, expires_at, ip, user_agent)`.
The token is `secrets.token_urlsafe(32)` in the `leapashore_session` cookie (`HttpOnly`, `SameSite=Lax`,
`Secure` when `APP_ENV=production`, 30 days); only its SHA-256 is stored, so a database read does not yield a
usable cookie. Logout deletes the row and clears the cookie. `SameSite=Lax` is the CSRF defence: every
state-changing route is a non-GET.

### D5. Client IP

`TRUST_FORWARDED_FOR=true` (production) takes the right-most `X-Forwarded-For` entry, the one Caddy writes
(Caddy ignores a client-supplied header unless `trusted_proxies` is configured, which it is not). Otherwise the
socket peer is used. The API port is not published in production, so only Caddy reaches it.

### D6. First login under concurrency

The account row is created with `INSERT … ON CONFLICT (email) DO NOTHING` and read back, so two concurrent
first logins for one email create one account; the loser merges into the winner (D7). The anonymous client
row is locked `FOR UPDATE` before it is claimed or merged, so one browser's data cannot be merged twice.

### D7. Anonymous merge and its conflict rules

The browser's `leapashore_client` cookie names the anonymous subject. It is considered only if the client row
exists and no account owns it. Then:

1. **New account** (this login created it): the account *claims* the anonymous client — `client_id` is set to
   it, no rows move. Otherwise a fresh client is created.
2. **Existing account, browser has anonymous data**: rows move into the account's client in one transaction,
   and the account's own rows always win:
   - **Profile** is treated as a unit, not field by field: if the account's profile has any answered field it
     is kept as it is and the anonymous profile is dropped; if it is empty, every anonymous field is copied.
     (Field-by-field filling can pair one profile's average with the other's scale.)
   - **Portfolio** (`applications`): an anonymous row for a program the account does not hold moves over
     with its band, status and deadline; a row for a program the account already holds is dropped. The moved
     row keeps `is_primary` only if the account has no first choice.
   - **Roadmap tasks**: a task whose `(material_key, program_id)` the account lacks moves; a duplicate is
     dropped, after every material pointing at it is re-pointed to the account's task.
   - **Materials** (`documents` and their versions and reviews) always move: a file is never a conflict.
   - **History** (`task_events`) always moves.
   - The anonymous client is then deleted; the cascade removes what was dropped.
3. The anonymous cookie is cleared on login, so after logout the browser starts a new anonymous subject
   instead of re-offering data that now belongs to an account.

Advisor conversations are in process memory (P1 moves them to PostgreSQL) and are not merged.

### D8. What needs a session in login mode

| Route | Logged out (login mode) |
| --- | --- |
| `/api/programs*`, `/api/universities`, `/api/review-criteria`, `/api/advisor/status`, `/api/health`, `/api/auth/*` | public |
| `GET /api/roadmap` | public; the definition with `tasks: []` |
| `/api/profile`, `/api/applications`, `/api/documents*`, roadmap task writes, `/api/advisor/chat`, `/api/advisor/confirm` | 401 `需要登录` |

All of them go through one dependency (`get_subject` / `get_optional_subject`), and the advisor tools read the
subject only from the graph config the router builds from it.

### D9. Deletion

`DELETE /api/auth/account` (body: the account's email, as a typed confirmation) and the 90-day sweep share
`delete_subject(session, client_id)`: collect the storage paths of the subject's document versions, delete the
client (cascade: profile, applications, tasks, events, documents, versions, reviews, findings, account,
sessions), delete the email's login codes, then unlink each blob no remaining version references. The
advisor's in-memory threads whose id starts with the client id are dropped too.

### D10. The 90-day sweep

`python -m app.cleanup [--apply]` deletes anonymous clients (no account) whose `last_seen_at` is older than 90
days, expired sessions, and login codes older than 2 days; without `--apply` it only reports. `last_seen_at`
is touched (at most once a day) whenever `load_or_create_profile` runs. Celery beat arrives in P1, so the
schedule is a host cron entry
(`17 3 * * * cd ~/offerpilot/deploy && sudo docker compose -f compose.prod.yaml exec -T api python -m app.cleanup --apply`),
installed when production switches to login mode — before that every subject is anonymous and nothing could
have been claimed.

### D11. Interface

- `AuthProvider` reads `GET /api/auth/me` once and exposes `requireLogin(): Promise<boolean>`. A gated action
  awaits it: the login dialog opens in place, and when it resolves the same handler continues with the values
  it captured (the advisor sends the typed sentence). No navigation, so nothing has to be stashed. A 401 from
  the server (an expired session) refreshes the auth state and goes through the same path.
- The dialog: email → code (60 s resend countdown) → on first registration, the four-field info step unless
  the merged profile already has them → done. The header's 登录 button then goes to `/tiers`.
- `/tiers` (moved from `/assess/result`) shows 先补信息 with the same four-field form inline when the basics
  are missing. `/me` edits every field and holds 退出登录 and 注销账号. `/assess` and `/assess/result`
  redirect to `/tiers`.
- Login-mode pages for private data (`/portfolio`, `/me`, `/tiers`) show a 登录后查看 panel when logged out;
  `/roadmap` shows the sample timeline.

### D12. Mail

`smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT=465)` with `SMTP_USER` / `SMTP_PASSWORD`, an `EmailMessage` from
`MAIL_FROM`. Tencent Cloud SES: host `smtp.qcloudmail.com` (Hong Kong region; `gz-smtp.qcloudmail.com` for
Guangzhou), port 465 implicit TLS, user = the sender address, password = the SMTP password set for it in the
console. A send failure answers 502 and the code still counts toward the limits.

## Risks / Trade-offs

- PostgreSQL-based rate limits cost a few queries per send; acceptable at this volume, and Redis replaces the
  advisor limits in the next item. → Counting is indexed on `(email, created_at)` and `(ip, created_at)`.
- A 6-digit code is guessable in principle. → One live code per email, 5 guesses, 10 codes a day.
- Mail can land in spam until SPF/DKIM/DMARC pass. → The DNS steps are in `note/handoff.md`.
- The privacy policy is a draft by Claude, not legal advice. → MortyYJT reviews it before login mode is on.

## Migration Plan

One Alembic revision adds the three tables. Deploy with `AUTH_ENABLED` unset: behaviour is unchanged. To
switch: SES + DNS + `SMTP_*`, `MAIL_BACKEND=smtp`, `AUTH_ENABLED=true` in `deploy/.env`, recreate the api
container, add the cron entry. Rollback: unset `AUTH_ENABLED`; the tables can stay.

## Open Questions

- The sender domain (proposed `mail.mortyyjt.site`, sender `noreply@mail.mortyyjt.site`) is MortyYJT's call
  at SES setup time; only `MAIL_FROM` depends on it.
