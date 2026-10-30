from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from revive_api.config import Config
from revive_api.control_plane import MemoryControlPlane
from revive_api.main import create_app
from revive_api.security import new_api_key
from revive_api.store import MemoryStore


@pytest.mark.asyncio
async def test_expired_api_key_is_rejected_by_the_memory_adapter() -> None:
    adapter = MemoryControlPlane(MemoryStore())
    user = await adapter.add_user("expired@example.com", "hash")
    value, prefix, digest = new_api_key()
    await adapter.add_api_key(
        user.id,
        prefix,
        digest,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert await adapter.find_api_key(value) is None


@pytest.mark.asyncio
async def test_future_api_key_is_still_accepted() -> None:
    adapter = MemoryControlPlane(MemoryStore())
    user = await adapter.add_user("future@example.com", "hash")
    value, prefix, digest = new_api_key()
    await adapter.add_api_key(
        user.id,
        prefix,
        digest,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    assert await adapter.find_api_key(value) is not None


def test_api_key_creation_returns_an_expiry() -> None:
    app = create_app(
        Config(
            jwt_secret="api-key-expiry-secret-at-least-32-characters",
            api_key_ttl_days=1,
        ),
        probes={},
    )
    client = TestClient(app)
    token = client.post(
        "/auth/register",
        json={"email": "keyexpiry@example.com", "password": "correct-horse-123"},
    ).json()["access_token"]
    response = client.post(
        "/auth/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"label": "cli"},
    )

    assert response.status_code == 201
    expires_at = response.json()["expires_at"]
    assert datetime.fromisoformat(expires_at.replace("Z", "+00:00")) > datetime.now(UTC)
