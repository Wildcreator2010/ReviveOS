"""Capsule builder must not package files linked from outside the source tree."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from revive_core.capsule.builder import RunState, build_entries
from revive_core.capsule.layout import SOURCE_TAR


def test_source_tar_skips_symlinks_that_point_outside_the_repo(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "app.py").write_text("print('ok')\n", encoding="utf-8")
    outside = tmp_path / "host-secret.txt"
    outside.write_text("HOST SECRET", encoding="utf-8")
    try:
        (source / "leak.txt").symlink_to(outside)
    except OSError:
        pytest.skip("creating symlinks is not permitted on this host")

    state = RunState(
        job_id="rev_job_symlink",
        source_repo="https://github.com/acme/demo",
        source_commit="abc1234",
        genome={},
        dockerfile="FROM python:3.11-slim\n",
        score={"total": 1.0, "components": {"runtime": 1.0}, "status": "partial"},
        created_at="2026-01-01T00:00:00Z",
        source_tree=source,
    )
    entries = dict(build_entries(state))

    with tarfile.open(fileobj=io.BytesIO(entries[SOURCE_TAR]), mode="r:") as archive:
        members = archive.getnames()

    assert "app.py" in members
    assert "leak.txt" not in members
