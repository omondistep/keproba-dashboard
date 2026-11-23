#!/usr/bin/env bash
# Nightly backup of BOTH Postgres databases (trade + Metabase app metadata).
# Usage: deploy/backup.sh /path/to/offbox/mount
set -euo pipefail

DEST="${1:?usage: backup.sh <destination-dir>}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DEST"

for db in "${POSTGRES_DB:-keproba}" metabase_app; do
  docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-keproba}" "$db" \
    | gzip > "${DEST}/${db}_${STAMP}.sql.gz"
done

# Keep 30 nightly snapshots.
find "$DEST" -name '*.sql.gz' -type f -mtime +30 -delete
echo "Backups written to $DEST at $STAMP"
