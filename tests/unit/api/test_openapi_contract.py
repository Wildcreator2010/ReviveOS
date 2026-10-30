"""Contract gates: the checked-in OpenAPI snapshot and the metrics surface.

`schemas/` is the repository's stated single source of truth, so a route change that
is not reflected in the snapshot must fail here instead of drifting silently.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from revive_api.config import Config
from revive_api.main import create_app

SNAPSHOT = Path("schemas/openapi/openapi.json")


def _app():
    return create_app(Config(jwt_secret="test-secret-at-least-32-bytes-long"), probes={})


def test_openapi_snapshot_matches_the_live_application() -> None:
    live = _app().openapi()
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert live == committed, "schemas/openapi/openapi.json is stale; run `python tools/export_openapi.py`"


def test_openapi_snapshot_exposes_the_contracted_api_surface() -> None:
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    paths = set(document["paths"])
    for required in (
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/api-keys",
        "/api/v1/me",
        "/api/v1/projects",
        "/api/v1/jobs",
        "/api/v1/capsules/{capsule_id}",
        "/api/v1/jobs/{job_id}/events/stream",
    ):
        assert required in paths, f"{required} missing from the OpenAPI snapshot"
    # Operational endpoints are internal and must stay out of the client contract.
    assert "/healthz" in paths
    assert "/metrics" not in paths


def test_metrics_endpoint_renders_prometheus_text() -> None:
    client = TestClient(_app())
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "revive_repair_success_ratio" in response.text


def test_openapi_declares_auth_schemes_and_protected_operations() -> None:
    document = _app().openapi()
    schemes = document["components"]["securitySchemes"]
    assert schemes["BearerAuth"]["scheme"] == "bearer"
    assert schemes["ApiKeyAuth"]["name"] == "X-Revive-Key"
    assert document["paths"]["/api/v1/jobs"]["get"]["security"] == [
        {"BearerAuth": []},
        {"ApiKeyAuth": []},
    ]
    assert "security" not in document["paths"]["/api/v1/auth/login"]["post"]
    assert document["paths"]["/api/v1/jobs/{job_id}/capsule"]["post"]["security"] == [{"WorkerTokenAuth": []}]


def test_capsule_download_documents_the_redirect() -> None:
    operation = _app().openapi()["paths"]["/api/v1/capsules/{capsule_id}/download"]["get"]
    assert "302" in operation["responses"]
