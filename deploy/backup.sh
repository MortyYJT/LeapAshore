#!/bin/sh
set -eu

backup_directory="${BACKUP_DIRECTORY:-/backups}"
retention_days="${BACKUP_RETENTION_DAYS:-7}"
interval_seconds="${BACKUP_INTERVAL_SECONDS:-86400}"
mkdir -p "$backup_directory"

create_backup() {
    timestamp="$(date -u +%Y%m%d-%H%M%S)"
    final_path="$backup_directory/offerpilot-$timestamp.dump"
    temporary_path="$final_path.incomplete"
    rm -f "$temporary_path"
    if pg_dump -h "${DB_HOST:-postgres}" -U "${DB_USER:-offerpilot}" -d "${DB_NAME:-offerpilot}" -Fc -f "$temporary_path"; then
        mv "$temporary_path" "$final_path"
        echo "backup_created path=$final_path"
    else
        rm -f "$temporary_path"
        echo "backup_failed" >&2
        return 1
    fi
    find "$backup_directory" -type f -name 'offerpilot-*.dump' -mtime "+$retention_days" -delete
}

create_backup
if [ "${BACKUP_ONCE:-false}" = "true" ]; then
    exit 0
fi

while sleep "$interval_seconds"; do
    create_backup || true
done
