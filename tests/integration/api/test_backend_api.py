"""Behavioral tests for the API's memory-backed control-plane seams."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from revive_api.config import Config
from revive_api.config_check import ConfigurationError
from revive_api.control_plane import MemoryControlPlane
from revive_api.main import create_app
from revive_api.store import MemoryStore


def test_production_app_fails_closed_without_durable_store() -> None:
    config = Config(environment="prod", jwt_secret="test-secret-at-least-32-bytes-long")
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        create_app(config, probes={})
    with pytest.raises(ConfigurationError, match="durable control-plane adapter"):
        create_app(config, probes={}, control_plane=MemoryControlPlane())


def test_production_app_requires_object_storage_configuration() -> None:
    config = Config(
        environment="prod",
        jwt_secret="test-secret-at-least-32-bytes-long",
        database_url="postgresql+asyncpg://revive@postgres/revive",
        redis_url="redis://redis:6379/0",
    )
    with pytest.raises(ConfigurationError, match="S3_ENDPOINT"):
        create_app(config, probes={})


def test_production_app_builds_the_durable_stack_from_configuration() -> None:
    config = Config(
        environment="prod",
        jwt_secret="test-secret-at-least-32-bytes-long",
        database_url="postgresql+asyncpg://revive@postgres/revive",
        redis_url="redis://redis:6379/0",
        s3_endpoint="http://minio:9000",
        s3_access_key="access",
        s3_secret_key="secret",
        s3_bucket="capsules",
    )
    app = create_app(config, probes={})
    assert app.state.control_plane.durable is True
    assert app.state.capsule_storage.durable is True


@pytest.fixture
def client() -> TestClient:
    return TestClient(
        create_app(Config(jwt_secret="test-secret-at-least-32-bytes-long"), probes={}, store=MemoryStore())
    )


def register(client: TestClient, email: str = "user@example.com", role: str = "user") -> tuple[str, str]:
    response = client.post("/auth/register", json={"email": email, "password": "correct-horse-123"})
    assert response.status_code == 201
    user_id = client.app.state.store.users_by_email[email]
    client.app.state.store.users[user_id].role = role
    return response.json()["access_token"], response.json()["refresh_token"]


def headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_projects_jobs_crud_dedup_and_pagination(client: TestClient) -> None:
    token, _ = register(client)
    auth = headers(token)
    created = client.post("/api/v1/projects", headers=auth, json={"repo_url": "https://github.com/Acme/Demo.git"})
    assert created.status_code == 201
    project = created.json()
    assert project["repo_url"] == "https://github.com/Acme/Demo"
    duplicate = client.post("/projects", headers=auth, json={"repository_url": "https://github.com/acme/demo"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["details"]["existing_id"] == project["id"]
    job = client.post(f"/projects/{project['id']}/resurrect", headers=auth)
    assert job.status_code == 202
    job_id = job.json()["job_id"]
    assert client.app.state.store.jobs[job_id].metadata["repo_url"] == project["repo_url"]
    status = client.get(f"/jobs/{job_id}", headers=auth).json()["status"]
    assert status in {"queued", "running", "succeeded"}
    assert client.get("/jobs?project_id=" + project["id"], headers=auth).json()["items"][0]["id"] == job_id
    cancelled = client.post(f"/jobs/{job_id}/cancel", headers=auth)
    assert cancelled.json()["cancel_requested"] is True
    assert client.delete(f"/projects/{project['id']}", headers=auth).status_code == 204
    assert client.get(f"/projects/{project['id']}", headers=auth).status_code == 404


def test_github_allowlist_authentication_and_uniform_errors(client: TestClient) -> None:
    rejected = client.post("/projects", json={"repository_url": "https://github.com.evil.example/a/b"})
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "repo_url_not_allowed"
    assert "request_id" in rejected.json()["error"]
    assert client.get("/projects").json()["error"]["code"] == "unauthorized"
    token, _ = register(client)
    key_response = client.post("/auth/api-keys", headers=headers(token), json={"name": "cli"})
    assert key_response.status_code == 201
    key = key_response.json()["key"]
    assert key not in repr(client.app.state.store.api_keys)
    assert client.get("/projects", headers={"X-Revive-Key": key}).status_code == 200


def test_refresh_rotation_reuse_revokes_family(client: TestClient) -> None:
    _, refresh_token = register(client)
    rotated = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert rotated.status_code == 200
    reused = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "refresh_reuse_detected"
    assert client.get("/projects", headers=headers(rotated.json()["access_token"])).status_code == 200


def test_logout_revokes_the_refresh_family(client: TestClient) -> None:
    _, refresh_token = register(client)
    rotated = client.post("/auth/refresh", json={"refresh_token": refresh_token}).json()

    assert client.post("/auth/logout", json={"refresh_token": rotated["refresh_token"]}).status_code == 204
    reused = client.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert reused.status_code == 401


def test_quota_evidence_and_capsule_download(client: TestClient) -> None:
    client.app.state.config = Config(jwt_secret="test-secret-at-least-32-bytes-long", max_concurrent_jobs=1)
    token, _ = register(client)
    auth = headers(token)
    project = client.post("/projects", headers=auth, json={"repo_url": "https://github.com/acme/one"}).json()
    first = client.post(f"/projects/{project['id']}/resurrect", headers=auth)
    assert first.status_code == 202
    over = client.post(f"/projects/{project['id']}/resurrect", headers=auth)
    assert over.status_code == 429
    assert over.headers["Retry-After"] == "60"
    # Mark the queued job terminal to free the concurrency slot.
    job = client.app.state.store.jobs[first.json()["job_id"]]
    job.status = "succeeded"
    add = client.post(
        f"/projects/{project['id']}/evidence",
        headers=auth,
        json={
            "source_kind": "manifest_file",
            "reference": "pyproject.toml",
            "facts": {"language": "python"},
            "confidence": 0.9,
            "excerpt": "private source",
        },
    )
    assert add.status_code == 201
    evidence = client.get(f"/projects/{project['id']}/evidence?source_kind=manifest_file", headers=auth).json()
    assert evidence["items"][0]["reference"] == "pyproject.toml"
    assert "private source" not in repr(evidence)
    content = b"capsule bytes"
    digest = hashlib.sha256(content).hexdigest()
    uploaded = client.post(
        f"/jobs/{job.id}/capsule",
        headers={"X-Worker-Token": "dev-worker-token"},
        json={"manifest": {"sha256": digest}, "content": base64.b64encode(content).decode()},
    )
    assert uploaded.status_code == 201
    capsule = uploaded.json()
    assert capsule["sha256"] == digest
    denied = client.get(f"/capsules/{capsule['id']}")
    assert denied.status_code == 401
    redirect = client.get(f"/capsules/{capsule['id']}/download", headers=auth, follow_redirects=False)
    assert redirect.status_code == 302
    assert redirect.headers["location"].startswith("/api/v1/capsules/")
    download_path = urlparse(redirect.headers["location"]).path + "?" + urlparse(redirect.headers["location"]).query
    download = client.get(download_path)
    assert download.content == content


def test_quota_inputs_cannot_be_rewritten_through_generic_project_metadata(client: TestClient) -> None:
    token, _ = register(client)
    auth = headers(token)
    project = client.post(
        "/projects", headers=auth, json={"repo_url": "https://github.com/acme/sized", "repo_size_mb": 12}
    ).json()
    assert client.app.state.store.projects[project["id"]].metadata["repo_size_mb"] == 12

    patched = client.patch(
        f"/projects/{project['id']}",
        headers=auth,
        json={"metadata": {"repo_size_mb": 0, "repo_key": "forged", "note": "kept"}},
    )
    assert patched.status_code == 200
    metadata = client.app.state.store.projects[project["id"]].metadata
    assert metadata["repo_size_mb"] == 12
    assert metadata["note"] == "kept"
    assert metadata.get("repo_key") != "forged"


def test_non_ascii_worker_token_never_becomes_a_server_error(client: TestClient) -> None:
    token, _ = register(client)
    auth = headers(token)
    project = client.post("/projects", headers=auth, json={"repo_url": "https://github.com/acme/unicode"}).json()
    job = client.post(f"/projects/{project['id']}/resurrect", headers=auth).json()["job_id"]

    response = client.post(
        f"/jobs/{job}/capsule",
        headers={b"X-Worker-Token": b"w\xf6rker"},
        json={"content": ""},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_resurrect_limits_are_persisted_and_invalid_values_rejected(client: TestClient) -> None:
    token, _ = register(client)
    auth = headers(token)
    project = client.post("/projects", headers=auth, json={"repo_url": "https://github.com/acme/limited"}).json()
    accepted = client.post(
        f"/projects/{project['id']}/resurrect",
        headers=auth,
        json={"budget_usd": 3.5, "timeout_seconds": 120},
    )
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    assert client.app.state.store.jobs[job_id].metadata["pipeline"] == {
        "budget_usd": 3.5,
        "timeout_seconds": 120,
        "max_repo_mb": 200,
    }

    rejected = client.post(
        f"/projects/{project['id']}/resurrect",
        headers=auth,
        json={"budget_usd": -1, "timeout_seconds": 0},
    )
    assert rejected.status_code == 422


def test_desktop_loopback_origin_is_allowed_by_cors(client: TestClient) -> None:
    response = client.options(
        "/projects",
        headers={
            "Origin": "http://127.0.0.1:54321",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:54321"


def test_api_v1_openapi_and_admin_maintenance(client: TestClient) -> None:
    token, _ = register(client, "admin@example.com", role="admin")
    auth = headers(token)
    assert client.get("/api/v1/projects", headers=auth).status_code == 200
    assert "/api/v1/projects" in client.app.openapi()["paths"]
    assert client.post("/admin/maintenance", headers=auth, json={"accepting_jobs": False}).json() == {
        "accepting_jobs": False
    }
    assert client.post("/projects", headers=auth, json={"repo_url": "https://github.com/acme/new"}).status_code == 201
    project_id = next(iter(client.app.state.store.projects))
    blocked = client.post(f"/projects/{project_id}/resurrect", headers=auth)
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "maintenance"
    assert client.app.state.store.admin_audit


def test_docker_integrations_are_not_falsely_claimed() -> None:
    store = MemoryStore()
    assert store.requires_docker is False
