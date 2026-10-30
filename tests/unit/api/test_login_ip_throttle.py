from __future__ import annotations

from fastapi.testclient import TestClient
from revive_api.config import Config
from revive_api.main import create_app


def test_login_lockout_also_keys_on_the_client_ip() -> None:
    client = TestClient(
        create_app(
            Config(
                jwt_secret="login-ip-throttle-secret-at-least-32-characters",
                login_failure_limit=2,
                login_lockout_minutes=5,
            ),
            probes={},
        )
    )
    assert (
        client.post(
            "/auth/register",
            json={"email": "victim@example.com", "password": "correct-horse-123"},
        ).status_code
        == 201
    )

    assert (
        client.post(
            "/auth/login",
            json={"email": "first@example.com", "password": "wrong-password"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login",
            json={"email": "second@example.com", "password": "wrong-password"},
        ).status_code
        == 401
    )

    blocked = client.post(
        "/auth/login",
        json={"email": "victim@example.com", "password": "correct-horse-123"},
    )
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]
