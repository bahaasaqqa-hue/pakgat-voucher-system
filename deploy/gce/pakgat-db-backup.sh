#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/backups/pakgat/postgres"
DB_NAME="${PAKGAT_DB_NAME:-pakgat_voucher}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/${DB_NAME}_${STAMP}.dump"

install -d -m 0700 "$BACKUP_DIR"
sudo -u postgres pg_dump --format=custom --no-owner --no-privileges --file="$OUT" "$DB_NAME"
chmod 0600 "$OUT"

# Keep seven days of local rolling backups. Off-VM backup is a separate step.
find "$BACKUP_DIR" -type f -name "${DB_NAME}_*.dump" -mtime +7 -delete

printf 'backup=%s bytes=%s\n' "$OUT" "$(stat -c %s "$OUT")"
