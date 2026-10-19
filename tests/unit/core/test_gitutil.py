"""git executable resolution contract."""

from __future__ import annotations

from pathlib import Path

import pytest
from revive_core import gitutil


def test_find_git_returns_an_executable():
    path = gitutil.find_git()
    assert Path(path).is_file()


def test_revive_git_bin_env_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = tmp_path / "git.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv(gitutil.GIT_BIN_ENV, str(fake))
    assert gitutil.find_git() == str(fake)


def test_missing_git_message_is_actionable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gitutil, "_candidates", lambda: ["/nope/git"])
    with pytest.raises(gitutil.GitUnavailableError) as excinfo:
        gitutil.find_git()
    assert gitutil.GIT_BIN_ENV in str(excinfo.value)


def test_run_git_failure_raises_git_error():
    with pytest.raises(gitutil.GitError):
        gitutil.run_git(["rev-parse", "--verify", "definitely-not-a-ref"])
