"""Contract tests for revive_core.gitutil (global env requirement).

The build machine may have no system git at all, so the contract is:
`REVIVE_GIT_BIN` wins, the workspace-local portable install is a fallback, and a
total miss raises an actionable `GitUnavailableError` -- never a bare
`FileNotFoundError`.
"""

from __future__ import annotations

import pytest
from revive_core import gitutil


def test_revive_git_bin_takes_priority(tmp_path, monkeypatch) -> None:
    fake_git = tmp_path / "git.exe"
    fake_git.write_text("", encoding="utf-8")
    monkeypatch.setenv(gitutil.GIT_BIN_ENV, str(fake_git))
    assert gitutil.find_git() == str(fake_git)


def test_missing_git_raises_actionable_error(monkeypatch) -> None:
    monkeypatch.setattr(gitutil, "_candidates", lambda: ["/definitely/not/a/git"])
    with pytest.raises(gitutil.GitUnavailableError) as excinfo:
        gitutil.find_git()
    message = str(excinfo.value)
    assert gitutil.GIT_BIN_ENV in message
    assert ".tools" in message or "PATH" in message


def test_run_git_returns_structured_output() -> None:
    result = gitutil.run_git(["--version"])
    assert result.ok
    assert "git version" in result.stdout


def test_run_git_failure_raises_git_error() -> None:
    with pytest.raises(gitutil.GitError):
        gitutil.run_git(["rev-parse", "--verify", "no-such-ref-reviveos"])
