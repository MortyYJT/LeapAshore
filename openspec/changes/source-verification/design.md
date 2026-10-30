## Context

TASKS.md P2 #3. `sources` is one official page; programs point at it (`programs.source_id`), the
importer adds a `source_versions` row per snapshot whose `body_text` holds the quotes that passed
`verify` (`[field] quote (出处: url)` per line), and deadlines keep their own quote on
`program_deadlines`. `snapshot_pages`/`snapshot_chunks` (P1 #5) hold the page text of the snapshot each
file cites (locally every one of the 7,425 imported pages has a snapshot page with the same sha). The
importer already resets `verified_at` to NULL when a page's content changes. `accounts.role = 'admin'`
exists (PR #67) and is granted only from the server shell (`python -m app.roles grant <email>`).

## Decisions

### D1. The unit of verification is the page at one snapshot

`verified_at` lives on `sources`, and the interface shows 已核验 per source. A person confirming "I read
these values against this page" is a statement about one page at one snapshot, so that is what is
recorded. The reading view lists every program the page backs with each field's stored value (English,
academic, Chinese-student marks, prerequisites, deadlines) and the quotes behind it; a field whose quote
passed but whose summary was blocked shows the quote with "未入库". A per-field date would need new
columns on five tables and a new meaning for 已核验 in the interface, for no gain the item asks for.

### D2. Confirming needs the exact snapshot the quotes came from

`POST …/verify` carries the `contentSha256` the person read. It is refused with 409 when the page's
latest version is a different sha (the page changed while they read), when there is no snapshot page with
that sha and some text (nothing to have read), or when the page is already verified. The snapshot shown
is the de-templated chunk text joined in order; shared pages the quotes cite are shown too, but only the
page's own snapshot is required.

### D3. Who and when: an append-only `source_verifications` table

One row per confirmation (`verify`) or withdrawal (`revoke`): `source_id` (CASCADE), `action`,
`content_sha256`, `account_id` (`ON DELETE SET NULL`: deleting the account removes who, not the fact),
`decided_at`, `txid` (`txid_current()` by default). The column is deliberately not called
`verified_at`, so the scan in D5 has one meaning per name. `sources.verified_at` is set to the same
moment. A withdrawal sets it back to NULL and `status` to 待核验.

### D4. A database guard: a trigger, not column privileges

The application connects as the owner of every table, so a column `GRANT` would not stop it; a second
database role would mean a second connection pool and a second secret for one button. Instead a
`BEFORE INSERT OR UPDATE` trigger on `sources` refuses (SQLSTATE 42501):

- `status = '已核验'` with a NULL `verified_at`;
- a non-null `verified_at` that is new (insert, or different from the old value) unless a
  `source_verifications` row with `action = 'verify'`, the same source, the same moment and
  `txid = txid_current()` exists, by an account whose role is `admin`.

Clearing the date is allowed for everyone: it only ever withdraws a claim (the importer does it when a
page changes). The guard is against code, not against someone with DDL rights: a superuser can drop it,
and `pg_restore` loads data before it creates triggers, so a restore is unaffected.

### D5. A static scan names every writer

`tests/test_verified_at_writers.py` parses every Python file under `api/` (not tests) and finds every
store to `.verified_at`, every `verified_at=` keyword, every `"verified_at"` dict key and `setattr`,
and every string that looks like SQL writing the column; it also greps the scripts. Each hit must be in
an allow-list that says whether it may write a value other than NULL. Only two may:
`services/source_verification.py` (this entry) and `services/reviews.py::verify_criterion` (the
existing operator command for material-review criteria, a separate table). A new writer fails the test
until someone adds it to the list with a reason.

### D6. The page is server-gated

`/admin` and `/admin/sources/[id]` are server components that ask `GET /api/admin/me` with the
request's session cookie and call `notFound()` on anything but 200, so in anonymous mode, logged out, or
as an applicant, the page is the ordinary 404 and the API answers 401/403. No navigation link points at
it.

### D7. The knowledge-gap queue goes on the same page

The review API exists (PR #67); listing open gaps with their questions and the two review buttons is a
small client component, so `/admin` shows both. Re-collection still needs the worker and broker.

### D8. How MortyYJT becomes admin

Unchanged from PR #67: after login mode is on, MortyYJT logs in once, then on the server
`sudo docker compose -f compose.prod.yaml exec -T api python -m app.roles grant <the email used>`. No
email is written in the repository.
