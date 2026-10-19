from __future__ import annotations

import json
from pathlib import Path

import httpx
from revive_cli.client import ReviveClient


def test_submit_resurrection_matches_api_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/projects":
            return httpx.Response(201, json={"id": "project-1", "repo_url": "https://github.com/o/r"})
        return httpx.Response(202, json={"job_id": "job-1", "status": "queued"})

    with ReviveClient("https://api.test", transport=httpx.MockTransport(handler)) as client:
        job = client.submit_resurrection("https://github.com/o/r")

    assert job.id == "job-1"
    assert job.project_id == "project-1"
    assert [request.url.path for request in requests] == [
        "/api/v1/projects",
        "/api/v1/projects/project-1/resurrect",
    ]
    assert json.loads(requests[0].content) == {"repo_url": "https://github.com/o/r"}


def test_api_key_and_sse_route_match_api_contract() -> None:
    seen: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen = request
        return httpx.Response(
            200,
            text='event: job.succeeded\ndata: {"type":"job.succeeded","payload":{"status":"succeeded"}}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    with ReviveClient("https://api.test", api_key="secret", transport=httpx.MockTransport(handler)) as client:
        events = list(client.stream_events("job-1"))

    assert seen is not None
    assert seen.url.path == "/api/v1/jobs/job-1/events/stream"
    assert seen.headers["X-Revive-Key"] == "secret"
    assert events[0].event == "job.succeeded"


def test_request_preserves_custom_headers_after_token_refresh() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/auth/refresh":
            return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh"})
        if len([item for item in requests if item.url.path == "/resource"]) == 1:
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json={"ok": True})

    with ReviveClient(
        "https://api.test",
        access_token="old-access",
        refresh_token="old-refresh",
        transport=httpx.MockTransport(handler),
    ) as client:
        response = client.request("GET", "/resource", headers={"X-Trace-Id": "trace-123"})

    assert response.status_code == 200
    resource_requests = [request for request in requests if request.url.path == "/resource"]
    assert len(resource_requests) == 2
    assert all(request.headers["X-Trace-Id"] == "trace-123" for request in resource_requests)
    assert resource_requests[0].headers["Authorization"] == "Bearer old-access"
    assert resource_requests[1].headers["Authorization"] == "Bearer new-access"


def test_download_capsule_resolves_latest_project_capsule(tmp_path: Path) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/v1/jobs/job-1":
            return httpx.Response(200, json={"id": "job-1", "project_id": "project-1", "status": "succeeded"})
        if request.url.path == "/api/v1/projects/project-1/capsules":
            return httpx.Response(200, json={"items": [{"id": "capsule-1"}], "next_cursor": None})
        return httpx.Response(200, content=b"capsule")

    target = tmp_path / "result.revive"
    with ReviveClient("https://api.test", transport=httpx.MockTransport(handler)) as client:
        result = client.download_capsule("job-1", target)

    assert result.read_bytes() == b"capsule"
    assert paths == [
        "/api/v1/jobs/job-1",
        "/api/v1/projects/project-1/capsules",
        "/api/v1/capsules/capsule-1/download",
    ]
