"""Shared PostgreSQL provisioning fixtures for the integration suite."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest
from db_provision import create_and_migrate, drop_database
from sqlalchemy.engine import URL


@pytest.fixture
def provision_database() -> Iterator[Callable[[str], URL]]:
    """Hand back a factory that creates, migrates and later drops throwaway schemas."""

    if not os.getenv("DATABASE_URL", "").strip():
        pytest.skip("DATABASE_URL is not set; start the dev compose postgres first")

    original = os.environ["DATABASE_URL"]
    created: list[str] = []

    def provision(name: str) -> URL:
        created.append(name)
        return create_and_migrate(name)

    yield provision

    for name in created:
        drop_database(name)
    os.environ["DATABASE_URL"] = original
