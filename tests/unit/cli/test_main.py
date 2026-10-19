from revive_cli.auth import Credentials, CredentialStore
from revive_cli.client import ReviveClient
from revive_cli.main import _persist_client_credentials, app
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
