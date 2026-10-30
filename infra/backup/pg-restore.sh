#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${BACKUP_FILE:?set BACKUP_FILE to the .sql.zst produced by pg-backup.sh}"
DATABASE_URL="${DATABASE_URL:?set DATABASE_URL}"
DATABASE_URL="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"
zstd -dc "$BACKUP_FILE" | psql "$DATABASE_URL"
