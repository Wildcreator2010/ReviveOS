"""PyPI historical release client with a disk cache.

Only pypi.org is reachable. Requests use a 10 second timeout, bounded
exponential backoff and a 24 hour on-disk cache. Recorded JSON fixtures are
injected through an httpx transport in tests.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog

from ..netguard import assert_safe_redirect, assert_safe_url

log = structlog.get_logger(__name__)

ALLOWED_PYPI_HOSTS = frozenset({"pypi.org"})
DEFAULT_BASE_URL = "https://pypi.org/pypi"
MAX_CONCURRENCY = 5
DEFAULT_TTL = timedelta(hours=24)


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("revive-core")
    except Exception:  # noqa: BLE001 - metadata may be absent in a source checkout
        return "0.1.0"


def _default_cache_dir() -> Path:
    override = os.environ.get("REVIVE_CACHE_DIR")
    base = Path(override) if override else Path.cwd() / ".revive-cache"
    return base / "pypi"


@dataclass(frozen=True)
class Release:
    version: str
    uploaded_at: datetime
    requires_python: str | None = None


class PackageNotFound(LookupError):
    """Raised only when a caller explicitly asks for a mandatory package."""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class PypiClient:
    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        ttl: timedelta = DEFAULT_TTL,
        timeout: float = 10.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        offline: bool = False,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        parsed = httpx.URL(self.base_url)
        if parsed.host not in ALLOWED_PYPI_HOSTS:
            raise ValueError(f"PyPI client may only talk to {sorted(ALLOWED_PYPI_HOSTS)}, got {parsed.host!r}")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else _default_cache_dir()
        self.ttl = ttl
        self.timeout = timeout
        self.max_retries = max(1, min(max_retries, 3))
        self.offline = offline
        self.user_agent = user_agent or f"reviveos/{_package_version()}"
        assert_safe_url(self.base_url, allowed_hosts=ALLOWED_PYPI_HOSTS)
        self._client = client or httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            follow_redirects=False,
        )

    # -- cache ---------------------------------------------------------------
    def _cache_path(self, package: str) -> Path:
        safe = package.replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, package: str) -> dict[str, Any] | None:
        path = self._cache_path(package)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        fetched_at = datetime.fromtimestamp(data.get("fetched_at", 0), tz=UTC)
        if datetime.now(UTC) - fetched_at > self.ttl:
            return None
        payload = data.get("payload")
        return payload if isinstance(payload, dict) else None

    def _write_cache(self, package: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(package)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"fetched_at": time.time(), "payload": payload}),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - cache is best effort
            log.warning("pypi.cache_write_failed", package=package, error=str(exc))

    # -- http ----------------------------------------------------------------
    def _request_json(self, package: str) -> dict[str, Any] | None:
        url = f"{self.base_url}/{package}/json"
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                assert_safe_url(url, allowed_hosts=ALLOWED_PYPI_HOSTS)
                response = self._client.get(url, follow_redirects=False)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    assert_safe_redirect(str(location), allowed_hosts=ALLOWED_PYPI_HOSTS)
                    response = self._client.get(str(location), follow_redirects=False)
            except httpx.HTTPError as exc:
                last_error = exc
                log.warning("pypi.request_failed", package=package, attempt=attempt, error=str(exc))
                time.sleep(min(0.5 * (2**attempt), 4.0))
                continue
            if response.status_code == 404:
                log.info("pypi.package_not_found", package=package, status=404)
                return None
            if response.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"server error {response.status_code}",
                    request=response.request,
                    response=response,
                )
                time.sleep(min(0.5 * (2**attempt), 4.0))
                continue
            if response.status_code != 200:
                log.warning("pypi.unexpected_status", package=package, status=response.status_code)
                return None
            try:
                data = response.json()
            except ValueError as exc:
                last_error = exc
                continue
            return data if isinstance(data, dict) else None
        if last_error is not None:
            log.warning("pypi.exhausted_retries", package=package, error=str(last_error))
        return None

    def fetch_payload(self, package: str) -> dict[str, Any] | None:
        cached = self._read_cache(package)
        if cached is not None:
            return cached
        if self.offline:
            log.info("pypi.offline_cache_miss", package=package)
            return None
        payload = self._request_json(package)
        if payload is not None:
            self._write_cache(package, payload)
        return payload

    # -- public API ----------------------------------------------------------
    def releases(self, name: str) -> list[Release]:
        payload = self.fetch_payload(name)
        if payload is None:
            return []
        raw = payload.get("releases")
        if not isinstance(raw, dict):
            return []
        releases: list[Release] = []
        for version, files in raw.items():
            if not isinstance(files, list):
                continue
            uploaded_at: datetime | None = None
            requires_python: str | None = None
            for entry in files:
                if not isinstance(entry, dict):
                    continue
                stamp = entry.get("upload_time_iso_8601") or entry.get("upload_time")
                parsed = _parse_dt(stamp)
                if parsed is not None and (uploaded_at is None or parsed < uploaded_at):
                    uploaded_at = parsed
                if requires_python is None and isinstance(entry.get("requires_python"), str):
                    requires_python = entry["requires_python"]
            if uploaded_at is None:
                continue
            releases.append(Release(version=str(version), uploaded_at=uploaded_at, requires_python=requires_python))
        releases.sort(key=lambda release: (release.uploaded_at, release.version))
        return releases

    def versions_before(self, name: str, cutoff: datetime) -> list[Release]:
        """Releases uploaded at or before cutoff, oldest first."""

        moment = _as_utc(cutoff)
        return [release for release in self.releases(name) if release.uploaded_at <= moment]

    def latest_before(self, name: str, cutoff: datetime) -> Release | None:
        candidates = self.versions_before(name, cutoff)
        if not candidates:
            return None
        return max(candidates, key=lambda release: release.uploaded_at)

    def close(self) -> None:
        self._client.close()


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


__all__ = [
    "ALLOWED_PYPI_HOSTS",
    "PackageNotFound",
    "PypiClient",
    "Release",
]
