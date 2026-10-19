"""Cross-process persistence: data written by one API instance is visible to another.

Runs only with a real PostgreSQL (`requires_docker`). It is the acceptance gate that
prevents the control plane from silently falling back to process-local memory.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from revive_api.config import Config
from revive_api.db.session import session_factory
from revive_api.db.uow import RequestControlPlane
from revive_api.main import create_app
from sqlalchemy.engine import URL

pytestmark = pytest.mark.requires_docker

TEST_DB = "revive_api_persistence_test"


def _config() -> Config:
    # `dev` keeps the Redis/object-storage adapters out of the way; the point of this
    # test is the PostgreSQL control plane, which is injected explicitly below.
    return Config(
        jwt_secret="test-secret-at-least-32-bytes-long",
        database_url="postgresql+asyncpg://unused/unused",
    )


def _app_for(url: URL) -> Any:
    def engine_factory(_: str):
        return session_factory(url.render_as_string(hide_password=False))

    return create_app(
        _config(),
        probes={},
        control_plane=RequestControlPlane(),
        engine_factory=engine_factory,
    )


def test_project_created_in_one_api_instance_is_visible_in_another(
    provision_database: Callable[[str], URL],
) -> None:
    url = provision_database(TEST_DB)

    first = TestClient(_app_for(url))
    with first:
        register = first.post(
            "/api/v1/auth/register",
            json={"email": "persist@example.com", "password": "correct-horse-123"},
        )
        assert register.status_code == 201
        token = register.json()["access_token"]
        created = first.post(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={"repository_url": "https://github.com/acme/persisted"},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

    second = TestClient(_app_for(url))
    with second:
        relogin = second.post(
            "/api/v1/auth/login",
            json={"email": "persist@example.com", "password": "correct-horse-123"},
        )
        assert relogin.status_code == 200
        token = relogin.json()["access_token"]
        projects = second.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
        assert projects.status_code == 200
        assert [item["id"] for item in projects.json()["items"]] == [project_id]
