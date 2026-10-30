from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import pytest
from revive_cli.auth import Credentials, CredentialStore
from revive_cli.client import ReviveClient
from revive_cli.main import _make_execution_port, _persist_client_credentials, app
from revive_core.sandbox.port_impl import LocalExecutionPort, SandboxUnavailableError
from typer.testing import CliRunner

runner = CliRunner()


def test_persist_client_credentials_keeps_api_key_and_extra(tmp_path) -> None:
    store = CredentialStore(tmp_path / "credentials.json")
    store.save(
        Credentials(
            access_token="old",
            refresh_token="old-r",
            server="https://api.test",
            api_key="key",
            extra={"profile": "dev"},
        )
    )
    client = ReviveClient("https://api.test", access_token="new", refresh_token="new-r")
    try:
        _persist_client_credentials(client, store)
    finally:
        client.close()
    saved = store.load()
    assert saved.access_token == "new"
    assert saved.refresh_token == "new-r"
    assert saved.api_key == "key"
    assert saved.extra == {"profile": "dev"}


def test_root_help_lists_command_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "analyze" in result.stdout
    assert "resurrect" in result.stdout
    assert "verify" in result.stdout
    assert "replay" in result.stdout
    assert "jobs" in result.stdout


def test_each_core_command_has_help() -> None:
    for command in ("analyze", "resurrect", "verify", "replay", "login", "jobs"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, (command, result.stdout, result.stderr)


def test_jobs_subcommands_have_help() -> None:
    for command in ("ls", "get"):
        result = runner.invoke(app, ["jobs", command, "--help"])
        assert result.exit_code == 0, (command, result.stdout, result.stderr)


def test_credentials_fallback_file_is_owner_only(tmp_path) -> None:
    store = CredentialStore(tmp_path / "credentials.json")
    store.save(Credentials(access_token="a", refresh_token="r", server="https://api.test"))

    assert store.path.is_file()
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600


def test_resurrect_server_mode_does_not_call_an_unfinished_stream_a_success(monkeypatch) -> None:
    class FakeClient:
        access_token = ""
        refresh_token = ""

        def submit_resurrection(self, repo_url, **options):
            return SimpleNamespace(id="job-1")

        def stream_events(self, job_id):
            return iter(())

        def get_job(self, job_id):
            return SimpleNamespace(status="running")

        def close(self) -> None:
            return None

    class FakeStore:
        def load(self):
            return Credentials(server="https://api.test")

    monkeypatch.setattr("revive_cli.main._client", lambda server: (FakeClient(), FakeStore()))
    result = runner.invoke(app, ["resurrect", "https://github.com/acme/demo", "--server", "https://api.test"])

    assert result.exit_code == 2
    assert "终态" in result.stdout or "终态" in result.stderr


def test_local_pipeline_refuses_host_execution_when_docker_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("revive_cli.main.docker_available", lambda: (False, "no daemon"))

    with pytest.raises(SandboxUnavailableError, match="Docker"):
        _make_execution_port(
            work_root=tmp_path,
            source=None,
            job_id="local-test",
            keep_sandbox=False,
            events=None,
        )


def test_local_pipeline_allows_host_execution_only_when_explicitly_requested(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("revive_cli.main.docker_available", lambda: (False, "no daemon"))

    port = _make_execution_port(
        work_root=tmp_path,
        source=None,
        job_id="local-test",
        keep_sandbox=False,
        events=None,
        allow_host_execution=True,
    )

    assert isinstance(port, LocalExecutionPort)
