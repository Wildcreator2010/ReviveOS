#!/usr/bin/env bash
set -euo pipefail
: "${BACKUP_DIR:?set BACKUP_DIR}"
mkdir -p "$BACKUP_DIR"
pg_dump "${DATABASE_URL:?set DATABASE_URL}" | zstd -T0 -o "$BACKUP_DIR/pg-$(date -u +%Y%m%dT%H%M%SZ).sql.zst"
