## Why

TASKS.md P2 #3. Every collected requirement is shown as 待核验 or 机器核对: `sources.verified_at` exists,
the interface already turns a set date into 已核验 ("有人对照官网核对过"), and the red line says only a
person may set it. Nothing lets a person do that. The item asks for an entry only MortyYJT's account can
use (the admin role on the account, added in PR #67), where a person reads each field, its quotes and
the page snapshot and then confirms, and for a test proving no other code path can write the field.

## What Changes

- **Schema (Alembic, add-only)**: `source_verifications` (one row per confirmation or withdrawal: source,
  the snapshot sha the person read, the admin account, the moment, the transaction id) and a trigger on
  `sources` that refuses a non-null `verified_at` unless the same transaction inserted a matching
  confirmation row by an account whose role is `admin`, and refuses `status = 已核验` without a date.
- **API** (admin accounts only; 401 without a session, 403 otherwise and always in anonymous mode):
  `GET /api/admin/me`, `GET /api/admin/verification` (pages that back imported programs, unverified
  first-by-use, searchable), `GET /api/admin/verification/{source_id}` (each program's fields with their
  stored values and quotes, the page's snapshot text and the shared pages its quotes cite, the history),
  `POST …/{source_id}/verify` (`contentSha256` of the version read) and `POST …/{source_id}/revoke`.
- **Web**: `/admin` (the verification list and the knowledge-gap queue) and `/admin/sources/[id]` (the
  reading view with the confirm button). Both answer 404 unless the request's session is an admin's.
- **Proof**: a static scan over the repository for every write to a `verified_at` column, checked
  against a short allow-list, and database tests showing the trigger refuses every other writer.

## Impact

- Code: `api/app/models/source.py`, `api/app/services/source_verification.py`, `api/app/routers/admin.py`,
  Alembic `c8e1f4a7b2d9`, `web/app/admin/`, `web/lib/admin.ts`, `scripts/walkthrough.cjs`.
- Ops: none. Production is in anonymous mode, so the page is 404 and the API 403 there until login mode
  is on and MortyYJT's account is granted the role with `python -m app.roles grant <email>`.
- Not in scope: verifying a single field (the unit is the page), editing or overriding a value the
  faithfulness check blocked (those never reach the database), `review_criteria.verified_at` (material
  review criteria; its existing operator command stays its only writer).
