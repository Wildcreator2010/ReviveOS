"""Alembic environment for the ReviveOS control plane (T-BE-02).

Migrations run on a synchronous psycopg connection: `DATABASE_URL` is written for
the async app driver (`postgresql+asyncpg://...`), so the driver is swapped here
rather than keeping a second, drifting connection string in `alembic.ini`.
"""

from __future__ import annotations

import os

from alembic import context
from revive_api.db.models import Base
from sqlalchemy import create_engine, pool

config = context.config
target_metadata = Base.metadata

# Migrations are PostgreSQL-only: JSONB and pgvector's vector column have no
# portable DDL, so an sqlite fallback would silently produce a broken schema.
_SYNC_DRIVER = "postgresql+psycopg"


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip() or (config.get_main_option("sqlalchemy.url") or "").strip()
    if not url:
        raise SystemExit(
            "DATABASE_URL is not set. Start the dev database with `make dev` (or export "
            "DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/revive) and re-run the migration."
        )
    if not url.startswith("postgresql"):
        raise SystemExit(f"migrations require a PostgreSQL URL, got {url.split('://')[0]!r}")
    scheme, rest = url.split("://", 1)
    if scheme != _SYNC_DRIVER:
        url = f"{_SYNC_DRIVER}://{rest}"
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=False,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
