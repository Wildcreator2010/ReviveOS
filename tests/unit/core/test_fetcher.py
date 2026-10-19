"""Git fetcher: host allowlist, token hygiene, full-history clone."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from revive_core.archaeology import fetcher
from revive_core.archaeology.fetcher import (
    ALLOWED_GIT_HOSTS,
    clone_args,
    fetch_repo,
    github_auth_env,
)


@pytest.fixture(autouse=True)
def _skip_dns(monkeypatch: pytest.MonkeyPatch):
    # netguard resolves DNS; the fetcher tests focus on policy, not egress.
    monkeypatch.setattr(fetcher, "assert_safe_url", lambda url, allowed_hosts=None: url)


def test_allowed_hosts_is_github_only():
    assert ALLOWED_GIT_HOSTS == frozenset({"github.com"})


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/org/repo.git",
        "https://bitbucket.org/org/repo",
        "https://github.com.evil.example/org/repo.git",
        "git@github.com:org/repo.git",
    ],
)
def test_non_github_remote_is_rejected(url: str):
    with pytest.raises(ValueError):
        fetcher._validate_remote_url(url)


def test_http_scheme_is_rejected():
    with pytest.raises(ValueError):
        fetcher._validate_remote_url("http://github.com/org/repo.git")


def test_embedded_credentials_are_rejected():
    secret = "tok" + "_" + "abcdef123456"
    with pytest.raises(ValueError):
        fetcher._validate_remote_url("https://user:" + secret + "@github.com/org/repo.git")


def test_missing_local_path_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        fetch_repo(str(tmp_path / "missing"), tmp_path / "clone")


def test_clone_args_request_full_history():
    args = clone_args("https://github.com/org/repo.git", Path("dest"))
    assert args[0] == "clone"
    assert "--tags" in args
    assert "--no-single-branch" in args
    assert not any(item.startswith("--depth") for item in args)
    assert "--" in args
    assert all("token" not in item.lower() for item in args)


def test_github_auth_env_none_without_token():
    assert github_auth_env(None) is None
    assert github_auth_env("") is None


def test_github_auth_env_uses_git_config_channel():
    token = "ghp_" + "B" * 36
    env = github_auth_env(token)
    assert env is not None
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    encoded = base64.b64encode(("x-access-token:" + token).encode("utf-8")).decode("ascii")
    assert env["GIT_CONFIG_VALUE_0"] == "Authorization: Basic " + encoded


def test_fetch_local_mirror(golden_repos: Path, tmp_path: Path):
    repo = golden_repos / "py27-flask"
    mirror = fetch_repo(str(repo), tmp_path / "clone")
    assert mirror.path == repo
    assert mirror.default_branch == "main"
    assert mirror.head_commit
    assert {tag.name for tag in mirror.tags} == {"v0.1.0", "v0.2.0"}
    assert all(tag.date is not None for tag in mirror.tags)
    assert mirror.remotes == []
    assert "main" in mirror.branches


def test_fetch_dot_git_path_resolves_worktree(golden_repos: Path, tmp_path: Path):
    mirror = fetch_repo(str(golden_repos / "py27-flask" / ".git"), tmp_path / "clone")
    assert mirror.path == golden_repos / "py27-flask"


def test_token_never_reaches_config_or_logs(golden_repos: Path, tmp_path: Path, capsys):
    token = "ghp_" + "C" * 36
    repo = golden_repos / "three-era-deps"
    mirror = fetch_repo(str(repo), tmp_path / "clone", github_token=token)
    config = (mirror.path / ".git" / "config").read_text(encoding="utf-8", errors="replace")
    assert token not in config
    assert token not in mirror.head_commit
    assert all(token not in remote for remote in mirror.remotes)
    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err


def test_not_a_git_repository_is_rejected(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ValueError):
        fetch_repo(str(plain), tmp_path / "clone")
