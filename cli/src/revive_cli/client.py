"""Thin httpx client for the ReviveOS control plane (T-CLI-01).

Hand-written for now (the generated OpenAPI client arrives with T-BE-03); the
contract tests exercise it against an httpx MockTransport so the wire shape is
pinned.  A 401 triggers exactly one refresh-and-retry.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from .sse import ServerEvent, parse_sse_lines


class ApiError(RuntimeError):
    def __init__(self, status_code: int, message: str, *, body: Any = None) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.body = body


class AuthError(ApiError):
    pass


@dataclass
class Job:
    id: str
    status: str = "queued"
    project_id: str = ""
    repo: str = ""
    score: float | None = None
    capsule_url: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Job:
        return cls(
            id=str(value.get("id", value.get("job_id", ""))),
            status=str(value.get("status", "queued")),
            project_id=str(value.get("project_id", "")),
            repo=str(value.get("repo", value.get("repo_url", ""))),
            score=(float(value["score"]) if value.get("score") is not None else None),
            capsule_url=value.get("capsule_url") or value.get("download_url"),
        )


class ReviveClient:
    def __init__(
        self,
        base_url: str,
        *,
        access_token: str = "",
        refresh_token: str = "",
        api_key: str = "",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.api_key = api_key
        kwargs: dict[str, Any] = {"base_url": self.base_url, "timeout": timeout}
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.Client(**kwargs)

    # -- plumbing --------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ReviveClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        elif self.api_key:
            headers["X-Revive-Key"] = self.api_key
        return headers

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        request_headers = kwargs.pop("headers", {})
        headers = {**self._headers(), **request_headers}
        response = self._client.request(method, path, headers=headers, **kwargs)
        if response.status_code == 401 and self.refresh_token:
            self._refresh()
            headers = {**self._headers(), **request_headers}
            response = self._client.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            body: Any
            try:
                body = response.json()
            except ValueError:
                body = response.text
            message = body.get("detail", body) if isinstance(body, dict) else body
            if response.status_code == 401:
                raise AuthError(response.status_code, str(message), body=body)
            raise ApiError(response.status_code, str(message), body=body)
        return response

    def _refresh(self) -> None:
        response = self._client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": self.refresh_token},
            headers={"Accept": "application/json"},
        )
        if response.status_code >= 400:
            raise AuthError(response.status_code, "token refresh failed", body=response.text)
        payload = response.json()
        self.access_token = str(payload.get("access_token", self.access_token))
        self.refresh_token = str(payload.get("refresh_token", self.refresh_token))

    # -- auth ------------------------------------------------------------
    def login_password(self, email: str, password: str) -> dict[str, Any]:
        response = self.request("POST", "/api/v1/auth/login", json={"email": email, "password": password})
        payload = cast(dict[str, Any], response.json())
        self.access_token = str(payload.get("access_token", ""))
        self.refresh_token = str(payload.get("refresh_token", ""))
        return payload

    # -- jobs ------------------------------------------------------------
    def submit_resurrection(self, repo_url: str, **options: Any) -> Job:
        project_payload = {"repo_url": repo_url}
        if "repo_size_mb" in options:
            project_payload["repo_size_mb"] = options.pop("repo_size_mb")
        project = self.request("POST", "/api/v1/projects", json=project_payload).json()
        project_id = str(project["id"])
        response = self.request("POST", f"/api/v1/projects/{project_id}/resurrect", json=options)
        payload = response.json()
        payload.setdefault("project_id", project_id)
        payload.setdefault("repo_url", repo_url)
        return Job.from_mapping(payload)

    def list_jobs(self) -> list[Job]:
        response = self.request("GET", "/api/v1/jobs")
        payload = response.json()
        items = payload.get("items", payload) if isinstance(payload, dict) else payload
        return [Job.from_mapping(item) for item in items]

    def get_job(self, job_id: str) -> Job:
        response = self.request("GET", f"/api/v1/jobs/{job_id}")
        return Job.from_mapping(response.json())

    def stream_events(self, job_id: str) -> Iterator[ServerEvent]:
        with self._client.stream(
            "GET",
            f"/api/v1/jobs/{job_id}/events/stream",
            headers={**self._headers(), "Accept": "text/event-stream"},
        ) as response:
            if response.status_code >= 400:
                raise ApiError(response.status_code, "event stream failed")
            yield from parse_sse_lines(response.iter_lines())

    def download_capsule(self, job_id: str, destination: str | Path) -> Path:
        job = self.get_job(job_id)
        url = job.capsule_url
        if not url:
            if not job.project_id:
                raise ApiError(409, "job has no project or capsule reference")
            capsules = self.request("GET", f"/api/v1/projects/{job.project_id}/capsules", params={"limit": 1}).json()
            items = capsules.get("items", []) if isinstance(capsules, dict) else []
            if not items:
                raise ApiError(404, "job has no downloadable capsule")
            url = f"/api/v1/capsules/{items[0]['id']}/download"
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("http"):
            with self._client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise ApiError(response.status_code, "capsule download failed")
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        else:
            response = self.request("GET", url)
            target.write_bytes(response.content)
        return target


__all__ = ["ApiError", "AuthError", "Job", "ReviveClient"]
