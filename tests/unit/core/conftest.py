"""Shared fixtures for the core archaeology test suite."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_REPOS = REPO_ROOT / "tests" / "fixtures" / "repos"
FIXTURE_PYPI = REPO_ROOT / "tests" / "fixtures" / "pypi"


def _locate_git() -> str | None:
    explicit = os.environ.get("REVIVE_GIT_BIN")
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("git")
    if found:
        return found
    for relative in ("cmd/git.exe", "bin/git", "bin/git.exe"):
        candidate = REPO_ROOT / ".tools" / "git" / relative
        if candidate.is_file():
            return str(candidate)
    return None


GIT_BIN = _locate_git()
if GIT_BIN:
    os.environ.setdefault("REVIVE_GIT_BIN", GIT_BIN)


@pytest.fixture(scope="session")
def git_bin() -> str:
    if GIT_BIN is None:
        pytest.skip("git executable unavailable; install git or set REVIVE_GIT_BIN")
    return GIT_BIN


@pytest.fixture(scope="session")
def golden_repos(git_bin: str) -> Path:
    if not (FIXTURE_REPOS / "three-era-deps" / ".git").exists():
        subprocess.run(
            [sys.executable, str(FIXTURE_REPOS / "make_fixtures.py")],
            check=True,
            env={**os.environ, "REVIVE_GIT_BIN": git_bin},
        )
    return FIXTURE_REPOS


@pytest.fixture(scope="session")
def numpy_payload() -> dict:
    return json.loads((FIXTURE_PYPI / "numpy.json").read_text(encoding="utf-8"))
