# account-auth Specification

## Purpose
Email-code sign-in: one-time 6-digit codes that are short-lived, single-use, guess-limited and rate-limited; server-side sessions; one account per email even under concurrent first sign-ins; mail only over SMTP in production; sign-in mode is a switch.
## Requirements
### Requirement: Login is by email and a one-time 6-digit code; the first login registers

`POST /api/auth/code` SHALL mail a 6-digit code to a valid email address. `POST /api/auth/verify` with that
email and code SHALL create a session and, when no account has that email, create the account. The response
SHALL say whether the account was created.

#### Scenario: First login registers

- **WHEN** a code is requested for `a@example.com` and verified
- **THEN** one account with email `a@example.com` exists, the response says `created: true`, and the response
  sets an httpOnly session cookie

#### Scenario: Email is normalised

- **WHEN** a code is requested for ` A@Example.COM ` and verified as `a@example.com`
- **THEN** it is the same account

### Requirement: A code is short-lived, single-use and guess-limited

A code SHALL expire 10 minutes after it is sent, SHALL be accepted at most once, and SHALL be invalidated
after 5 wrong guesses. Requesting a new code SHALL invalidate older codes for the same email.

#### Scenario: An expired code is refused

- **WHEN** a code older than 10 minutes is submitted
- **THEN** the answer is 400 `code_expired` and no session is created

#### Scenario: A used code is refused

- **WHEN** a code that already logged in is submitted again
- **THEN** the answer is 400 `code_expired`

#### Scenario: Guessing is cut off at five

- **WHEN** five wrong codes are submitted for an email, then the right one
- **THEN** the fifth answer is `too_many_attempts` and the right code is refused

#### Scenario: Concurrent guesses do not exceed the limit

- **WHEN** twenty wrong guesses for one code arrive at the same time
- **THEN** at most five are counted against it and every one is refused

### Requirement: Sending codes is rate-limited

A code SHALL NOT be sent to an email within 60 seconds of the previous one. An email and an IP address SHALL
each have a configurable daily cap on codes sent (defaults: 10 per email, 30 per IP, over a rolling 24 hours).
A refused send SHALL answer 429 with the seconds to wait.

#### Scenario: Resend too soon

- **WHEN** a second code is requested for the same email 10 seconds after the first
- **THEN** the answer is 429 with `retryAfter` of about 50 and no mail is sent

#### Scenario: Daily cap per email

- **WHEN** the email has reached its daily cap
- **THEN** further requests answer 429 until the oldest code in the window is 24 hours old

#### Scenario: Daily cap per IP

- **WHEN** one IP has reached its daily cap across different emails
- **THEN** the next request from it answers 429

### Requirement: Sessions are server-side and can be ended

A session SHALL be a row in PostgreSQL keyed by the hash of a random token held in an httpOnly cookie, valid
for 30 days. `POST /api/auth/logout` SHALL delete the row and clear the cookie.

#### Scenario: Logout ends the session

- **WHEN** a logged-in browser logs out and then reads `/api/profile` with the old cookie
- **THEN** the read answers 401

### Requirement: Concurrent first logins create one account

Account creation SHALL be idempotent per email under concurrency.

#### Scenario: Two first logins race

- **WHEN** two verifications for the same new email complete at the same time
- **THEN** exactly one account row exists for that email and both browsers are logged in to it

### Requirement: Mail goes through SMTP; the log backend is never used in production

The `smtp` mail backend SHALL send through the configured SMTP server with the Python standard library. The
`log` backend SHALL only write the code to the log. With `APP_ENV=production` and login mode on, the API SHALL
refuse to start unless the `smtp` backend and its credentials are configured, and the `log` backend SHALL
refuse to send.

#### Scenario: Production refuses the log backend

- **WHEN** settings say `APP_ENV=production`, `AUTH_ENABLED=true`, `MAIL_BACKEND=log`
- **THEN** the startup check raises naming the missing configuration

### Requirement: Login mode is a switch

With `AUTH_ENABLED` off the API SHALL behave as before this change (anonymous cookie subjects), the auth write
routes SHALL answer 404, and `GET /api/auth/me` SHALL say `authEnabled: false`.

#### Scenario: Switch off

- **WHEN** login mode is off and a client calls `POST /api/auth/code`
- **THEN** the answer is 404 and no code is stored

