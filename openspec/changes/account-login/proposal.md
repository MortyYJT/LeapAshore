## Why

Every applicant is an anonymous cookie today. Clearing the browser, switching devices or using a second
browser loses the profile, the portfolio and the materials; nothing ties the data to a person, so it cannot
be deleted on request, and the next items (per-account rate limits and token budgets, the admin-only
verification entry) need an identity that is more than a cookie. The background assessment (`/assess`) is
also a ten-question gate in front of the product: the tiers need only four facts, and the rest belongs on
the applicant's own page.

## What Changes

- **Email + 6-digit code login**, first login registers. Codes expire after 10 minutes, are single-use,
  die after 5 wrong guesses and cannot be resent within 60 seconds; each email and each IP has a daily send
  cap. Sessions live in PostgreSQL behind an httpOnly cookie; logout deletes the session.
- **Mail through Tencent Cloud SES over SMTP** with the standard library (`smtplib`), no new dependency. The
  `log` mail backend (local and CI) only writes the code to the log; production refuses to start with it
  while login is on.
- **Login mode is a switch** (`AUTH_ENABLED`). Off (production until MortyYJT has SES, DNS and SMTP
  credentials): today's anonymous behaviour. On: browsing (home, schools, programs, the sample roadmap, the
  advisor page) needs no login; any write, and any read of the applicant's own data, needs a session. The
  interface opens a login dialog at the point of the action and finishes the action afterwards (the advisor
  sends the sentence that was typed). Pressing 登录 directly lands on the tiers page.
- **`/assess` is removed.** After the first registration the dialog asks for four facts — undergraduate
  school, average mark, target field, English score — and can be skipped. The other fields (education level,
  major, degree, intake, budget) are edited on 我的. The tiers page moves to `/tiers` and tells a user who
  skipped to 先补信息. **BREAKING** for bookmarks of `/assess` and `/assess/result` (both redirect).
- **Anonymous data merge**: on a browser's first login its anonymous profile, portfolio, roadmap tasks and
  materials move into the account; rows the account already has are never overwritten. Anonymous data no one
  claims is deleted 90 days after it was last used.
- **Every endpoint and every advisor tool resolves the subject from the session** in login mode; one account
  can neither read nor write another's rows.
- **Account deletion** removes every row and uploaded file that belongs to the account.
- **Privacy policy page** `/privacy`, drafted by Claude, to be reviewed by MortyYJT.

## Capabilities

### New Capabilities

- `account-auth`: email-code login, sessions, logout, rate limits, mail delivery, the login-mode switch.
- `account-data-scope`: which routes need a session, and isolation between accounts, including advisor tools.
- `anonymous-merge`: claiming a browser's anonymous data at first login, the conflict rules, the 90-day sweep.
- `profile-basics`: the four-field info step that replaces `/assess`, and the 先补信息 state on the tiers page.
- `privacy-policy`: the policy page and account deletion.

### Modified Capabilities

- `background-assessment` (from `ledger-redesign`): the ten-question page is retired; see `profile-basics`.

## Impact

- **Database (add-only)**: new tables `accounts`, `auth_sessions`, `login_codes`. No existing column changes;
  `clients.last_seen_at` (already present) starts being updated.
- **API**: new `/api/auth/*` routes; every route that used `get_client_id` resolves its subject through one
  dependency that honours the switch.
- **Config**: `AUTH_ENABLED`, `APP_ENV`, `MAIL_BACKEND`, `SMTP_*`, `MAIL_FROM`, `TRUST_FORWARDED_FOR`, limits.
- **Web**: auth context, login dialog, `/tiers`, `/privacy`, editable 我的; `/assess*` redirect.
- **Operations**: MortyYJT must open SES, verify a sender domain in DNSPod and put the SMTP credentials into
  `deploy/.env` before login mode is switched on in production; the 90-day sweep is a host cron entry added
  at the same time.
