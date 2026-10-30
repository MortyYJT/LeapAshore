# account-data-scope Specification

## Purpose
In sign-in mode every private route needs a session, and an account can read or write only its own data subject.
## Requirements
### Requirement: Private routes need a session in login mode

In login mode, `/api/profile`, `/api/applications`, `/api/documents` and its sub-routes, roadmap task writes,
`/api/advisor/chat` and `/api/advisor/confirm` SHALL answer 401 without a valid session. The program and
university catalogue, the review criteria, `/api/advisor/status` and `GET /api/roadmap` SHALL stay public;
`GET /api/roadmap` without a session SHALL return the definition with no tasks.

#### Scenario: Logged-out write is refused

- **WHEN** login mode is on and a request without a session sends `PATCH /api/profile`
- **THEN** the answer is 401 and no client or profile row is created

#### Scenario: Catalogue stays public

- **WHEN** login mode is on and a request without a session reads `/api/programs`
- **THEN** the answer is 200

### Requirement: One account cannot reach another's data

Every private route and every advisor tool SHALL resolve the subject from the session alone. An anonymous
cookie SHALL be ignored for subject resolution in login mode.

#### Scenario: A cannot read B

- **WHEN** account B has a profile, a portfolio row and a material, and account A reads `/api/profile`,
  `/api/applications`, `/api/documents` and `/api/documents/{B's id}`
- **THEN** A sees only its own data and B's material answers 404

#### Scenario: An anonymous cookie does not grant access

- **WHEN** login mode is on and a request carries B's former anonymous cookie but no session
- **THEN** private routes answer 401

#### Scenario: Advisor tools are scoped

- **WHEN** the advisor runs `get_my_profile` for account A
- **THEN** it reads A's profile and not B's

