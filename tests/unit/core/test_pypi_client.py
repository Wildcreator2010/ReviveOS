"""PyPI client: recorded fixtures, cutoff semantics, cache, retries, egress."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from packaging.version import Version
from revive_core.archaeology import pypi_client
from revive_core.archaeology.pypi_client import ALLOWED_PYPI_HOSTS, PypiClient

CUTOFF = datetime(2018, 6, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _skip_dns(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pypi_client, "assert_safe_url", lambda url, allowed_hosts=None: url)
    monkeypatch.setattr(pypi_client, "assert_safe_redirect", lambda url, allowed_hosts=None: url)


def _transport(payload: dict, calls: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def test_allowed_hosts_is_pypi_only():
    assert ALLOWED_PYPI_HOSTS == frozenset({"pypi.org"})


def test_numpy_cutoff_excludes_117_and_later(numpy_payload: dict, tmp_path: Path):
    client = PypiClient(cache_dir=tmp_path, transport=_transport(numpy_payload))
    before = client.versions_before("numpy", CUTOFF)
    assert before
    assert all(Version(release.version) < Version("1.17") for release in before)
    every = client.releases("numpy")
    assert Version("1.17.0") in {Version(release.version) for release in every}


def test_versions_before_is_sorted_and_returns_release_metadata(numpy_payload: dict, tmp_path: Path):
    client = PypiClient(cache_dir=tmp_path, transport=_transport(numpy_payload))
    before = client.versions_before("numpy", CUTOFF)
    uploads = [release.uploaded_at for release in before]
    assert uploads == sorted(uploads)
    assert all(release.uploaded_at.tzinfo is not None for release in before)
    assert all(release.requires_python is None or isinstance(release.requires_python, str) for release in before)


def test_disk_cache_avoids_a_second_request(numpy_payload: dict, tmp_path: Path):
    calls: list = []
    client = PypiClient(cache_dir=tmp_path, transport=_transport(numpy_payload, calls))
    assert client.releases("numpy")
    assert client.releases("numpy")
    assert len(calls) == 1
    assert (tmp_path / "numpy.json").exists()


def test_404_returns_empty_and_logs_package_not_found(tmp_path: Path, capsys):
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    client = PypiClient(cache_dir=tmp_path, transport=transport)
    assert client.releases("definitely-not-a-real-package") == []
    assert "pypi.package_not_found" in capsys.readouterr().out


def test_retries_then_succeeds(numpy_payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pypi_client.time, "sleep", lambda seconds: None)
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(500)
        return httpx.Response(200, json=numpy_payload)

    client = PypiClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler), max_retries=3)
    assert client.releases("numpy")
    assert len(attempts) == 3


def test_retries_are_bounded_to_three(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pypi_client.time, "sleep", lambda seconds: None)
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503)

    client = PypiClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler), max_retries=9)
    assert client.releases("numpy") == []
    assert len(attempts) == 3


def test_user_agent_is_reviveos(numpy_payload: dict, tmp_path: Path):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, json=numpy_payload)

    client = PypiClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    client.releases("numpy")
    assert seen and seen[0].startswith("reviveos/")


def test_offline_mode_never_calls_the_network(numpy_payload: dict, tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("offline client must not issue requests")

    client = PypiClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler), offline=True)
    assert client.releases("numpy") == []


def test_offline_mode_reads_a_warm_cache(numpy_payload: dict, tmp_path: Path):
    warm = PypiClient(cache_dir=tmp_path, transport=_transport(numpy_payload))
    warm.releases("numpy")
    cold = PypiClient(
        cache_dir=tmp_path,
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
        offline=True,
    )
    assert cold.releases("numpy")


def test_non_pypi_base_url_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        PypiClient(cache_dir=tmp_path, base_url="https://evil.example/pypi")


def test_latest_before_picks_the_newest_eligible(numpy_payload: dict, tmp_path: Path):
    client = PypiClient(cache_dir=tmp_path, transport=_transport(numpy_payload))
    latest = client.latest_before("numpy", CUTOFF)
    assert latest is not None
    assert Version(latest.version) < Version("1.17")
    earlier = client.versions_before("numpy", CUTOFF)
    assert latest.version == max(earlier, key=lambda release: release.uploaded_at).version
