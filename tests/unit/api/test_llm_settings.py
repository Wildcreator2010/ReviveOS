"""Admin-managed LLM settings: masked reads, validation, and the test probe."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from revive_agents.llm import FakeProvider
from revive_api.config import Config
from revive_api.main import create_app
from revive_api.secrets import decrypt_secret, encrypt_secret
from revive_api.store import MemoryStore
from revive_api.tasks import pipeline


def _client() -> TestClient:
    return TestClient(
        create_app(Config(jwt_secret="test-secret-at-least-32-bytes-long"), probes={}, store=MemoryStore())
    )


def _admin(client: TestClient, email: str = "admin@example.com") -> dict[str, str]:
    response = client.post("/auth/register", json={"email": email, "password": "correct-horse-123"})
    assert response.status_code == 201
    user_id = client.app.state.store.users_by_email[email]
    client.app.state.store.users[user_id].role = "admin"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_llm_settings_are_admin_only_and_masked() -> None:
    client = _client()
    user = client.post("/auth/register", json={"email": "user@example.com", "password": "correct-horse-123"}).json()
    denied = client.get("/admin/llm", headers={"Authorization": f"Bearer {user['access_token']}"})
    assert denied.status_code == 403

    auth = _admin(client)
    initial = client.get("/api/v1/admin/llm", headers=auth)
    assert initial.status_code == 200
    assert initial.json()["api_key_set"] is False

    missing_key = client.put(
        "/api/v1/admin/llm",
        headers=auth,
        json={"provider": "custom", "base_url": "https://llm.example/v1", "model": "demo-model"},
    )
    assert missing_key.status_code == 400

    saved = client.put(
        "/api/v1/admin/llm",
        headers=auth,
        json={
            "provider": "custom",
            "base_url": "https://llm.example/v1",
            "model": "demo-model",
            "api_key": "sk-secret-key",
            "reasoning_effort": "low",
        },
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["provider"] == "custom"
    assert payload["model"] == "demo-model"
    assert payload["api_key_set"] is True
    assert payload["api_key_hint"] == "…-key"
    assert "sk-secret-key" not in saved.text

    reread = client.get("/api/v1/admin/llm", headers=auth)
    assert reread.json()["api_key_hint"] == "…-key"
    assert "sk-secret-key" not in reread.text
    stored = client.app.state.store.runtime_settings["llm"]
    assert "api_key" not in stored
    assert decrypt_secret(stored["api_key_enc"]) == "sk-secret-key"


def test_fake_provider_can_be_selected_and_tested_without_network() -> None:
    client = _client()
    auth = _admin(client)
    saved = client.put("/api/v1/admin/llm", headers=auth, json={"provider": "fake"})
    assert saved.status_code == 200
    tested = client.post("/api/v1/admin/llm/test", headers=auth)
    assert tested.status_code == 200
    assert tested.json()["ok"] is True
    assert tested.json()["provider"] == "fake"


@pytest.mark.asyncio
async def test_worker_loads_the_runtime_provider() -> None:
    class Repository:
        async def get_runtime_setting(self, key: str) -> dict[str, Any]:
            assert key == "llm"
            return {"provider": "fake"}

    store = type("Store", (), {"repository": Repository()})()
    provider = await pipeline._configured_provider(store)
    assert isinstance(provider, FakeProvider)


def test_provider_secret_roundtrip_and_tamper_detection() -> None:
    encrypted = encrypt_secret("sk-roundtrip")
    assert "sk-roundtrip" not in encrypted
    assert decrypt_secret(encrypted) == "sk-roundtrip"
    tampered = encrypted[:-2] + ("AA" if encrypted[-2:] != "AA" else "BB")
    try:
        decrypt_secret(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("tampered ciphertext must be rejected")
