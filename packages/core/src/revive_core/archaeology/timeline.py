"""Git history archaeology: dependency/runtime snapshots over time."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import structlog

from ..gitutil import run_git
from .evidence import EvidenceItem, ExtractContext, extract_from_text

log = structlog.get_logger(__name__)

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
MAX_MESSAGE_CHARS = 280


@dataclass
class Snapshot:
    commit_sha: str
    date: datetime
    author: str | None = None
    path_changes: dict[str, list[EvidenceItem]] = field(default_factory=dict)
    message: str | None = None

    def first(self, path: str) -> EvidenceItem | None:
        items = self.path_changes.get(path)
        return items[0] if items else None


class Timeline(list):
    """A list of Snapshot with the extra derived fields from the contract."""

    def __init__(self, snapshots: list[Snapshot] | None = None) -> None:
        super().__init__(snapshots or [])
        self.last_activity: datetime | None = None
        self.death_candidates: list[tuple[str, datetime]] = []

    @property
    def snapshots(self) -> list[Snapshot]:
        return list(self)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _git_show(repo: Path, sha: str, path: str) -> str | None:
    result = run_git(["-C", str(repo), "show", f"{sha}:{path}"], check=False, timeout=60)
    if result.returncode != 0:
        return None
    return result.stdout


def discover_watched_paths(mirror) -> list[str]:
    """Tracked files that any extractor would care about."""

    from .extractors import matching_modules

    repo = Path(mirror.path)
    result = run_git(["-C", str(repo), "ls-tree", "-r", "--name-only", "HEAD"], check=False, timeout=120)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line and matching_modules(line)]


def _parse_log(repo: Path, stdout: str, watched: set[str]) -> list[Snapshot]:
    snapshots: list[Snapshot] = []
    for chunk in stdout.split(RECORD_SEP):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        lines = chunk.split("\n")
        header = lines[0].split(FIELD_SEP)
        if len(header) < 5:
            continue
        sha, author_date, committer_date, author, subject = header[:5]
        date = _parse_dt(committer_date) or _parse_dt(author_date) or datetime.now(UTC)
        path_changes: dict[str, list[EvidenceItem]] = {}
        for raw_path in lines[1:]:
            path = raw_path.strip()
            if not path or path not in watched:
                continue
            text = _git_show(repo, sha, path)
            if text is None:
                continue
            ctx = ExtractContext(
                commit_sha=sha,
                read_file=partial(_git_show, repo, sha),
            )
            items = extract_from_text(path, text, ctx)
            if items:
                path_changes[path] = items
        if path_changes:
            snapshots.append(
                Snapshot(
                    commit_sha=sha,
                    date=date,
                    author=author or None,
                    path_changes=path_changes,
                    message=subject[:MAX_MESSAGE_CHARS],
                )
            )
    return snapshots


def _death_candidates(repo: Path) -> list[tuple[str, datetime]]:
    result = run_git(
        [
            "-C",
            str(repo),
            "for-each-ref",
            f"--format=%(refname:short){FIELD_SEP}%(creatordate:iso-strict)",
            "refs/tags",
        ],
        check=False,
    )
    if result.returncode != 0:
        return []
    candidates: list[tuple[str, datetime]] = []
    for line in result.stdout.splitlines():
        if FIELD_SEP not in line:
            continue
        name, date_text = line.split(FIELD_SEP, 1)
        date = _parse_dt(date_text)
        if date is None:
            continue
        count = run_git(["-C", str(repo), "rev-list", "--count", f"{name}..HEAD"], check=False)
        if count.returncode == 0 and count.stdout.strip() == "0":
            candidates.append((name, date))
    return sorted(candidates, key=lambda item: item[1])


def build_timeline(mirror, watched_paths: list[str] | None = None) -> Timeline:
    """Return chronological snapshots for the watched manifest/CI paths."""

    repo = Path(mirror.path)
    watched = list(watched_paths) if watched_paths is not None else discover_watched_paths(mirror)
    watched_set = set(watched)
    snapshots: list[Snapshot] = []
    if watched:
        fmt = f"{RECORD_SEP}%H{FIELD_SEP}%aI{FIELD_SEP}%cI{FIELD_SEP}%an{FIELD_SEP}%s"
        result = run_git(
            ["-C", str(repo), "log", f"--format={fmt}", "--name-only", "--", *watched],
            check=False,
            timeout=600,
        )
        if result.returncode == 0:
            snapshots = _parse_log(repo, result.stdout, watched_set)
        else:
            log.warning("timeline.git_log_failed", error=result.stderr.strip()[:200])
    snapshots.sort(key=lambda snapshot: snapshot.date)

    timeline = Timeline(snapshots)
    last = run_git(["-C", str(repo), "log", "-1", "--format=%cI"], check=False)
    if last.returncode == 0:
        timeline.last_activity = _parse_dt(last.stdout.strip())
    if timeline.last_activity is None and snapshots:
        timeline.last_activity = snapshots[-1].date
    timeline.death_candidates = _death_candidates(repo)
    return timeline


__all__ = [
    "Snapshot",
    "Timeline",
    "build_timeline",
    "discover_watched_paths",
]
