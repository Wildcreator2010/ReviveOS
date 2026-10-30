#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${BACKUP_DIR:?set BACKUP_DIR}"
mkdir -p "$BACKUP_DIR"
# pg_dump/libpq does not understand SQLAlchemy's +asyncpg driver suffix.
DATABASE_URL="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"
pg_dump "$DATABASE_URL" | zstd -T0 -o "$BACKUP_DIR/pg-$(date -u +%Y%m%dT%H%M%SZ).sql.zst"
