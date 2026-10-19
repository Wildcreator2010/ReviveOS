"""Shared PostgreSQL provisioning for the integration suite.

Every durable test gets its own throwaway database (created, migrated to head,
dropped) so nothing competes with the dev `revive` schema and a failed run cannot
leave rows behind.  Import the helpers directly when a test needs to re-run
alembic mid-test; use the `provision_database` fixture in conftest otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url

REPO_ROOT = Path(__file__).resolve().parents[3]


def sync_url(database: str) -> URL:
    """Migrations need the psycopg driver regardless of what DATABASE_URL carries."""

    return make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+psycopg", database=database)


def async_url(database: str) -> URL:
    return sync_url(database).set(drivername="postgresql+asyncpg")


def alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "alembic"))
    config.set_main_option("prepend_sys_path", str(REPO_ROOT / "apps" / "api" / "src"))
    return config


def open_engine(url: URL) -> Engine:
    return create_engine(url.render_as_string(hide_password=False))


def admin_engine() -> Engine:
    return create_engine(sync_url("postgres").render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")


def create_and_migrate(database: str) -> URL:
    admin = admin_engine()
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    admin.dispose()

    os.environ["DATABASE_URL"] = sync_url(database).render_as_string(hide_password=False)
    command.upgrade(alembic_config(), "head")
    return async_url(database)


def drop_database(database: str) -> None:
    os.environ["DATABASE_URL"] = sync_url(database).render_as_string(hide_password=False)
    command.downgrade(alembic_config(), "base")
    admin = admin_engine()
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
    admin.dispose()
