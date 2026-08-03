#!/bin/sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"

if [ "${RESTORE_SMOKE_CONFIRM_EPHEMERAL:-}" != "1" ]; then
    echo "restore_smoke_refused: set RESTORE_SMOKE_CONFIRM_EPHEMERAL=1 only for an ephemeral test database" >&2
    exit 2
fi

python_bin="${PYTHON_BIN:-python3}"
for required_command in psql pg_dump pg_restore createdb dropdb "$python_bin"; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "restore_smoke_missing_command command=$required_command" >&2
        exit 2
    fi
done

source_database="$(
    psql --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --dbname="$DATABASE_URL" --command='SELECT current_database()'
)"
case "$source_database" in
    ""|postgres|template0|template1)
        echo "restore_smoke_refused source_database=$source_database" >&2
        exit 2
        ;;
esac

source_database_slug="$(printf '%s' "$source_database" | tr -c '[:alnum:]_' '_' | cut -c1-28)"
restore_database="op_restore_${source_database_slug}_$$"
restore_url="$(
    "$python_bin" - "$DATABASE_URL" "$restore_database" <<'PY'
import sys
from urllib.parse import quote, urlsplit, urlunsplit

source_url = urlsplit(sys.argv[1])
if source_url.scheme not in {"postgres", "postgresql"} or not source_url.netloc:
    raise SystemExit("DATABASE_URL must be a postgresql:// or postgres:// URL")
print(urlunsplit((
    source_url.scheme,
    source_url.netloc,
    "/" + quote(sys.argv[2], safe=""),
    source_url.query,
    source_url.fragment,
)))
PY
)"

scratch_root="${TMPDIR:-/tmp}"
scratch_directory="$(mktemp -d "$scratch_root/offerpilot-restore-smoke.XXXXXX")"
backup_path="$scratch_directory/source.dump"
source_manifest="$scratch_directory/source.manifest"
restore_manifest="$scratch_directory/restore.manifest"
restore_database_created=0

cleanup() {
    cleanup_exit=$?
    trap - EXIT HUP INT TERM
    if [ "$restore_database_created" -eq 1 ]; then
        if ! dropdb --maintenance-db="$DATABASE_URL" --if-exists --force "$restore_database"; then
            echo "restore_smoke_cleanup_failed database=$restore_database" >&2
            if [ "$cleanup_exit" -eq 0 ]; then
                cleanup_exit=1
            fi
        fi
    fi
    rm -f "$backup_path" "$source_manifest" "$restore_manifest"
    rmdir "$scratch_directory" 2>/dev/null || true
    exit "$cleanup_exit"
}
trap cleanup EXIT HUP INT TERM

psql --no-psqlrc --set=ON_ERROR_STOP=1 --dbname="$DATABASE_URL" <<'SQL'
BEGIN;
INSERT INTO users (
    id, email, display_name, password_hash, email_verified_at, role, status,
    created_at, last_login_at, terms_accepted_at, terms_version
) VALUES (
    'restore-smoke-user', 'restore-smoke@invalid.example', 'Restore Smoke',
    'restore-smoke-password-hash', NOW(), 'user', 'active', NOW(), NOW(), NOW(), 'restore-smoke'
) ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name;

INSERT INTO sessions (token, user_id, expires_at, created_at)
VALUES ('restore-smoke-session', 'restore-smoke-user', NOW() + INTERVAL '1 hour', NOW())
ON CONFLICT (token) DO UPDATE SET expires_at = EXCLUDED.expires_at;

INSERT INTO auth_tokens (token_hash, user_id, purpose, expires_at, created_at)
VALUES ('restore-smoke-auth-token', 'restore-smoke-user', 'verify_email', NOW() + INTERVAL '1 hour', NOW())
ON CONFLICT (token_hash) DO UPDATE SET expires_at = EXCLUDED.expires_at;

INSERT INTO entities (user_id, kind, entity_id, payload, created_at, updated_at)
VALUES (
    'restore-smoke-user', 'restore_smoke', 'restore-smoke-entity',
    '{"kind":"restore-smoke","version":1}'::jsonb, NOW(), NOW()
) ON CONFLICT (user_id, kind, entity_id)
DO UPDATE SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at;

INSERT INTO feedback (feedback_id, user_id, payload, created_at, updated_at)
VALUES (
    'restore-smoke-feedback', 'restore-smoke-user',
    '{"id":"restore-smoke-feedback","status":"open"}'::jsonb, NOW(), NOW()
) ON CONFLICT (feedback_id)
DO UPDATE SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at;

INSERT INTO program_source_versions (
    version_id, program_slug, source_id, content_hash, base_hash, status,
    payload, submitted_at, reviewed_at
) VALUES (
    'restore-smoke-source-version', 'restore-smoke-program', 'restore-smoke-source',
    repeat('a', 64), NULL, 'pending_review', '{"restore_smoke":true}'::jsonb, NOW(), NULL
) ON CONFLICT (version_id)
DO UPDATE SET payload = EXCLUDED.payload, submitted_at = EXCLUDED.submitted_at;
COMMIT;
SQL

manifest_query="SELECT relation_name, row_count, primary_keys
FROM (
    SELECT 'alembic_version'::text AS relation_name, COUNT(*) AS row_count,
           COALESCE(jsonb_agg(version_num ORDER BY version_num), '[]'::jsonb)::text AS primary_keys
    FROM alembic_version
    UNION ALL
    SELECT 'auth_tokens', COUNT(*),
           COALESCE(jsonb_agg(token_hash ORDER BY token_hash), '[]'::jsonb)::text
    FROM auth_tokens
    UNION ALL
    SELECT 'entities', COUNT(*),
           COALESCE(
               jsonb_agg(jsonb_build_array(user_id, kind, entity_id) ORDER BY user_id, kind, entity_id),
               '[]'::jsonb
           )::text
    FROM entities
    UNION ALL
    SELECT 'feedback', COUNT(*),
           COALESCE(jsonb_agg(feedback_id ORDER BY feedback_id), '[]'::jsonb)::text
    FROM feedback
    UNION ALL
    SELECT 'program_source_versions', COUNT(*),
           COALESCE(jsonb_agg(version_id ORDER BY version_id), '[]'::jsonb)::text
    FROM program_source_versions
    UNION ALL
    SELECT 'sessions', COUNT(*),
           COALESCE(jsonb_agg(token ORDER BY token), '[]'::jsonb)::text
    FROM sessions
    UNION ALL
    SELECT 'users', COUNT(*),
           COALESCE(jsonb_agg(id ORDER BY id), '[]'::jsonb)::text
    FROM users
) AS manifest
ORDER BY relation_name;"

capture_manifest() {
    psql --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --dbname="$1" --command="$manifest_query" > "$2"
}

capture_manifest "$DATABASE_URL" "$source_manifest"
pg_dump --dbname="$DATABASE_URL" --format=custom --file="$backup_path"
createdb --maintenance-db="$DATABASE_URL" "$restore_database"
restore_database_created=1
pg_restore --dbname="$restore_url" --exit-on-error --no-owner --no-privileges "$backup_path"
capture_manifest "$restore_url" "$restore_manifest"

if ! diff -u "$source_manifest" "$restore_manifest"; then
    echo "restore_smoke_manifest_mismatch source_database=$source_database restored_database=$restore_database" >&2
    exit 1
fi

echo "restore_smoke_passed source_database=$source_database restored_database=$restore_database tables=7"
