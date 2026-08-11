#!/bin/sh
set -eu

export PGPASSWORD="${DB_PASSWORD}"

BACKUP_DIR="${BACKUP_DIR:-/backups}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

echo "[backup] starting: interval=${INTERVAL}s retention=${RETENTION_DAYS}d dir=${BACKUP_DIR}"

while true; do
  timestamp=$(date -u +%Y%m%d-%H%M%S)
  target="$BACKUP_DIR/inventory-$timestamp.sql.gz"
  tmp="$target.tmp"

  echo "[backup] $(date -u +%FT%TZ) dumping $DB_NAME from $DB_HOST:$DB_PORT -> $target"
  if pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" | gzip > "$tmp"; then
    mv "$tmp" "$target"
    echo "[backup] $(date -u +%FT%TZ) done ($(du -h "$target" | cut -f1))"
  else
    echo "[backup] $(date -u +%FT%TZ) FAILED" >&2
    rm -f "$tmp"
  fi

  find "$BACKUP_DIR" -name 'inventory-*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -print -delete

  sleep "$INTERVAL"
done
