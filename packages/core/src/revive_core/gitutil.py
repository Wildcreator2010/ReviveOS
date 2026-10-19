"""Resolve and invoke the git executable.

ReviveOS never vendors git. Callers may point at an explicit binary through the
REVIVE_GIT_BIN environment variable; otherwise we look on PATH and finally at a
workspace-local portable install. When nothing is found we raise
GitUnavailableError with an actionable message instead of letting a bare
FileNotFoundError escape.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

GIT_BIN_ENV = "REVIVE_GIT_BIN"


class GitError(RuntimeError):
    """Base class for git failures raised by ReviveOS."""


class GitUnavailableError(GitError):
    """Raised when no usable git executable can be located."""


@dataclass(frozen=True)
class GitResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _candidates() -> list[str]:
    candidates: list[str] = []
    explicit = os.environ.get(GIT_BIN_ENV)
    if explicit:
        candidates.append(explicit)
    which = shutil.which("git")
    if which:
        candidates.append(which)
    # A portable install may live in a .tools/git folder near the checkout.
    for parent in Path(__file__).resolve().parents:
        candidates.append(str(parent / ".tools" / "git" / "cmd" / "git.exe"))
        candidates.append(str(parent / ".tools" / "git" / "bin" / "git"))
        candidates.append(str(parent / ".tools" / "git" / "bin" / "git.exe"))
    return candidates


def find_git() -> str:
    """Return the path of a usable git executable or raise GitUnavailableError."""

    for candidate in _candidates():
        if candidate and Path(candidate).is_file():
            return candidate
    raise GitUnavailableError(
        "git executable not found: set REVIVE_GIT_BIN to the git binary or add git to PATH "
        "(portable git is expected at .tools/git/cmd/git.exe)."
    )


def run_git(
    args: list[str] | tuple[str, ...],
    *,
    cwd: str | Path | None = None,
    check: bool = True,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> GitResult:
    """Run git without a shell and capture UTF-8 output."""

    exe = find_git()
    cmd = [exe, *[str(a) for a in args]]
    proc_env = dict(os.environ) if env is None else dict(env)
    try:
        proc = subprocess.run(
            cmd,
            cwd=None if cwd is None else str(cwd),
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=proc_env,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - defensive
        raise GitError(f"git {' '.join(str(a) for a in args)} timed out after {timeout}s") from exc
    result = GitResult(
        args=tuple(str(a) for a in args),
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
    if check and proc.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:400]
        raise GitError(f"git {' '.join(result.args)} failed ({proc.returncode}): {detail}")
    return result
