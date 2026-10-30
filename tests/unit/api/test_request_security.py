from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError
from revive_api.config import Config
from revive_api.main import create_app
from revive_api.schemas import RegisterRequest


def _app(**overrides):
    config = Config(
        jwt_secret="request-security-secret-at-least-32-characters",
        worker_token="w" * 40,
        max_request_bytes=1024,
        max_capsule_bytes=2048,
        **overrides,
    )
    return create_app(config, probes={})


def test_capsule_upload_rejects_missing_worker_token_before_json_validation() -> None:
    client = TestClient(_app())
    response = client.post(
        "/api/v1/jobs/job-1/capsule",
        content=b"not-json" + b"x" * 4096,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_capsule_upload_rejects_oversized_worker_body() -> None:
    client = TestClient(_app())
    response = client.post(
        "/api/v1/jobs/job-1/capsule",
        content=b"{}" + b" " * 4096,
        headers={"Content-Type": "application/json", "X-Worker-Token": "w" * 40},
    )
    assert response.status_code == 413


def test_regular_endpoint_rejects_oversized_body() -> None:
    client = TestClient(_app())
    response = client.post(
        "/auth/register",
        content=b'{"email":"a@b.example","password":"' + b"x" * 4096 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_validation_errors_do_not_echo_password_input() -> None:
    try:
        RegisterRequest(email="a@b.example", password="q7")
    except ValidationError as exc:
        errors = exc.errors()
    else:  # pragma: no cover - the fixture must be invalid
        raise AssertionError("expected a validation error")
    assert any("input" in error for error in errors)
    from revive_api.main import _safe_validation_errors

    sanitized = _safe_validation_errors(errors)
    assert "q7" not in str(sanitized)
    assert all("input" not in error and "ctx" not in error and "url" not in error for error in sanitized)
