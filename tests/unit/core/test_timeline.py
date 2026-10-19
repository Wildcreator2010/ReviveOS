"""Git history timeline archaeology."""

from __future__ import annotations

from pathlib import Path

from revive_core.archaeology import build_timeline, discover_watched_paths, fetch_repo
from revive_core.archaeology.timeline import Timeline


def _mirror(golden_repos: Path, name: str):
    return fetch_repo(str(golden_repos / name), golden_repos / ("unused-" + name))


def test_three_era_timeline_has_exactly_three_snapshots(golden_repos: Path):
    mirror = _mirror(golden_repos, "three-era-deps")
    timeline = build_timeline(mirror, ["requirements.txt"])
    assert isinstance(timeline, Timeline)
    assert len(timeline) == 3
    eras = []
    for snapshot in timeline:
        items = snapshot.path_changes["requirements.txt"]
        eras.append({dep["name"]: dep["version"] for dep in items[0].facts["dependencies"]})
    assert eras[0] == {"django": "1.8.2", "requests": "2.7.0"}
    assert eras[1] == {"django": "2.0.5", "requests": "2.19.1"}
    assert eras[2] == {"django": "3.2.5", "requests": "2.26.0"}


def test_timeline_is_chronological_with_metadata(golden_repos: Path):
    mirror = _mirror(golden_repos, "three-era-deps")
    timeline = build_timeline(mirror, ["requirements.txt"])
    dates = [snapshot.date for snapshot in timeline]
    assert dates == sorted(dates)
    assert timeline.last_activity is not None
    assert timeline.last_activity.year == 2021
    assert [tag for tag, _ in timeline.death_candidates] == ["v3.0"]
    assert all(snapshot.message and len(snapshot.message) <= 280 for snapshot in timeline)
    assert all(snapshot.commit_sha for snapshot in timeline)


def test_snapshot_first_helper(golden_repos: Path):
    mirror = _mirror(golden_repos, "three-era-deps")
    timeline = build_timeline(mirror, ["requirements.txt"])
    first = timeline[0].first("requirements.txt")
    assert first is not None
    assert first.reference.commit_sha == timeline[0].commit_sha
    assert timeline[0].first("setup.py") is None


def test_no_watched_paths_yields_empty_timeline(golden_repos: Path):
    mirror = _mirror(golden_repos, "three-era-deps")
    timeline = build_timeline(mirror, [])
    assert list(timeline) == []
    assert timeline.last_activity is not None


def test_discover_watched_paths(golden_repos: Path):
    mirror = _mirror(golden_repos, "py27-flask")
    watched = discover_watched_paths(mirror)
    assert "requirements.txt" in watched
    assert "setup.py" in watched
    assert "Dockerfile" in watched
    assert "README.md" in watched
    assert "app.py" not in watched


def test_history_snapshots_carry_commit_sha(golden_repos: Path):
    mirror = _mirror(golden_repos, "py27-flask")
    timeline = build_timeline(mirror, ["requirements.txt"])
    assert len(timeline) == 3
    for snapshot in timeline:
        items = snapshot.path_changes["requirements.txt"]
        assert items[0].reference.commit_sha == snapshot.commit_sha
