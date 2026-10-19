"""Git repository fetcher.

Only https://github.com remotes or existing local paths are accepted. Shallow
clones are forbidden because history is evidence. Tokens travel through git's
GIT_CONFIG_* environment channel, so they never appear in the clone URL or in
.git/config.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import structlog

from ..gitutil import run_git
from ..netguard import assert_safe_url

log = structlog.get_logger(__name__)

ALLOWED_GIT_HOSTS = frozenset({"github.com"})

_FIELD = "\x1f"


@dataclass
class TagInfo:
    name: str
    commit_sha: str = ""
    date: datetime | None = None


@dataclass
class RepoMirror:
    path: Path
    default_branch: str = ""
    tags: list[TagInfo] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    remotes: list[str] = field(default_factory=list)
    head_commit: str = ""
    cloned_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _looks_remote(url: str) -> bool:
    return "://" in url or url.startswith("git@")


def github_auth_env(token: str | None) -> dict[str, str] | None:
    """Return an environment that authenticates git without touching config."""

    if not token:
        return None
    env = dict(os.environ)
    payload = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
    env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {payload}"
    return env


def _validate_remote_url(url: str) -> None:
    assert_safe_url(url, allowed_hosts=ALLOWED_GIT_HOSTS)
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"only https:// github.com repositories are allowed, got scheme {parsed.scheme!r}: {url}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_GIT_HOSTS:
        raise ValueError(f"host {host!r} is not allowed; allowed hosts: {sorted(ALLOWED_GIT_HOSTS)}")
    if parsed.username or parsed.password:
        raise ValueError("credentials must not be embedded in the repository URL; pass github_token instead")


def _local_repo_root(url: str) -> Path:
    path = Path(url)
    if not path.exists():
        raise ValueError(f"local repository path does not exist: {url}")
    if path.name == ".git":
        return path.parent
    return path


def _mirror_from_repository(path: Path, *, cloned_at: datetime) -> RepoMirror:
    def git(*args: str, check: bool = True) -> str:
        return run_git(["-C", str(path), *args], check=check, timeout=120).stdout

    probe = run_git(["-C", str(path), "rev-parse", "--absolute-git-dir"], check=False)
    git_dir: Path | None = Path(probe.stdout.strip()) if probe.stdout.strip() else None
    if git_dir is not None and not git_dir.is_absolute():
        git_dir = path / git_dir
    if probe.returncode != 0 or git_dir is None or not git_dir.is_dir():
        raise ValueError(f"not a git repository: {path}")

    head_commit = git("rev-parse", "HEAD").strip()
    default_branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if default_branch == "HEAD":
        default_branch = git("symbolic-ref", "--short", "-q", "HEAD", check=False).strip()

    branches = [
        line.strip()
        for line in git("for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()
        if line.strip()
    ]
    remotes = [line.strip() for line in git("remote").splitlines() if line.strip()]

    tags: list[TagInfo] = []
    tag_lines = git(
        "for-each-ref",
        f"--format=%(refname:short){_FIELD}%(objectname){_FIELD}%(creatordate:iso-strict)",
        "refs/tags",
    )
    for line in tag_lines.splitlines():
        parts = line.split(_FIELD)
        if len(parts) < 2:
            continue
        tags.append(
            TagInfo(
                name=parts[0],
                commit_sha=parts[1],
                date=_parse_dt(parts[2]) if len(parts) > 2 else None,
            )
        )

    return RepoMirror(
        path=path,
        default_branch=default_branch,
        tags=tags,
        branches=branches,
        remotes=remotes,
        head_commit=head_commit,
        cloned_at=cloned_at,
    )


def clone_args(url: str, dest: Path) -> list[str]:
    """Full-history clone argv. A token is never part of this list."""

    return ["clone", "--no-single-branch", "--tags", "--quiet", "--", url, str(dest)]


def fetch_repo(url: str, dest: Path, *, github_token: str | None = None) -> RepoMirror:
    """Materialise a full-history mirror of a repository or mirror a local path."""

    destination = Path(dest)
    if _looks_remote(url):
        _validate_remote_url(url)
        if destination.exists() and any(destination.iterdir()):
            raise ValueError(f"clone destination already exists and is not empty: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        env = github_auth_env(github_token)
        log.info(
            "fetch_repo.clone",
            url=url,
            dest=str(destination),
            authenticated=bool(github_token),
        )
        run_git(clone_args(url, destination), check=True, timeout=1800, env=env)
        return _mirror_from_repository(destination, cloned_at=_now())

    root = _local_repo_root(url)
    # Reject paths that are not a git worktree. Note: `git rev-parse` walks up
    # parent directories looking for .git, so it can incorrectly succeed when the
    # caller runs the fetcher from inside a parent repo. Checking for a literal
    # .git entry in the path (or a `.git` file pointing elsewhere, as in
    # worktrees and submodules) is the only reliable local check.
    probe = run_git(["-C", str(root), "rev-parse", "--show-toplevel"], check=False)
    toplevel = probe.stdout.strip() if probe.stdout else ""
    toplevel_path = Path(toplevel) if toplevel else None
    has_git_entry = (root / ".git").exists()
    if not has_git_entry and (toplevel_path is None or toplevel_path != root.resolve()):
        raise ValueError(f"not a git repository: {root}")
    log.info("fetch_repo.local", path=str(root), authenticated=bool(github_token))
    return _mirror_from_repository(root, cloned_at=_now())


__all__ = [
    "ALLOWED_GIT_HOSTS",
    "TagInfo",
    "RepoMirror",
    "clone_args",
    "fetch_repo",
    "github_auth_env",
]
