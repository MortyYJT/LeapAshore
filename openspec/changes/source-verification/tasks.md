## Progress checklist

Branch `claude/source-verification`.

- [x] 1.1 Alembic (add-only): `source_verifications`, the `sources` guard trigger
- [x] 1.2 `app.services.source_verification`: list, detail, verify, revoke
- [x] 1.3 `/api/admin/me`, `/api/admin/verification…`
- [x] 1.4 Static writer scan and trigger tests; importer test uses a real confirmation
- [x] 1.5 Web `/admin`, `/admin/sources/[id]` (server-gated), `lib/admin.ts`; walkthrough admin vs applicant
- [x] 2.1 `make verify`; review (2 bugs fixed: same-snapshot value changes and the import/confirm race); deploy with backup
