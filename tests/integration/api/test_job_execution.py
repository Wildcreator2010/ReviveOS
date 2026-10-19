from __future__ import annotations

import time

from fastapi.testclient import TestClient
from revive_api.config import Config
from revive_api.main import create_app
from revive_api.store import MemoryStore


def test_resurrection_runs_to_capsule_and_publishes_terminal_event() -> None:
    client = TestClient(
        create_app(Config(jwt_secret="test-secret-at-least-32-bytes-long"), probes={}, store=MemoryStore())
    )
    registered = client.post("/auth/register", json={"email": "runner@example.com", "password": "correct-horse-123"})
    auth = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    project = client.post("/projects", headers=auth, json={"repo_url": "https://github.com/acme/runner"}).json()
    job_id = client.post(f"/projects/{project['id']}/resurrect", headers=auth).json()["job_id"]

    deadline = time.monotonic() + 3
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/jobs/{job_id}", headers=auth).json()["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.05)

    assert status == "succeeded"
    events = client.get(f"/jobs/{job_id}/events", headers=auth).json()
    assert events[-1]["type"] == "job.succeeded"
    capsules = client.get(f"/projects/{project['id']}/capsules", headers=auth).json()["items"]
    assert len(capsules) == 1
    assert client.get(f"/projects/{project['id']}/score", headers=auth).json()["score"]["status"] == "partial"
