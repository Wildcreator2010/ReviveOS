"""The worker must produce a real, verifiable capsule and upload it."""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path
from typing import Any

import pytest
from revive_agents.graph import GraphState
from revive_api.store import JobRecord
from revive_api.tasks import pipeline
from revive_core.behavior.capture import BehaviorPlan


@pytest.mark.asyncio
async def test_capsule_builder_uploads_a_verified_archive(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "README.md").write_text("# demo\n", encoding="utf-8")
    (source / "requirements.txt").write_text("requests==2.32.3\n", encoding="utf-8")
    job = JobRecord(id="rev_job_capsule", project_id="rev_project_1", user_id="rev_user_1")
    job.metadata["repo_url"] = "https://github.com/acme/demo"
    uploads: list[tuple[str, Path, dict[str, Any], str]] = []

    async def uploader(job_id: str, path: Path, manifest: dict[str, Any], sha256: str) -> str:
        uploads.append((job_id, path, manifest, sha256))
        return "rev_capsule_uploaded"

    state = GraphState(
        job_id=job.id,
        genome={"python": {"version": "3.11", "confidence": 0.9}, "dependencies": []},
        score={"total": 100.0, "components": {"tests": 1.0}},
        behavior_plan=BehaviorPlan(cases=[]),
        behavior_compatibility=1.0,
        status="succeeded",
    )

    ref = await pipeline._capsule_builder(job, source, tmp_path, [], uploader)(state)

    assert ref == "capsule://rev_capsule_uploaded"
    assert len(uploads) == 1
    uploaded_job, path, manifest, digest = uploads[0]
    assert uploaded_job == job.id
    assert path.is_file() and digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert manifest["source"] == {"repo": "https://github.com/acme/demo", "commit": "unknown"}
    assert manifest["status"] == "alive"
    with tarfile.open(path, "r:gz") as archive:
        names = set(archive.getnames())
    assert {"manifest.json", "digests.json", "source.tar", "dependencies.lock"} <= names


@pytest.mark.asyncio
async def test_capsule_builder_without_uploader_returns_a_local_uri(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    job = JobRecord(id="rev_job_local_capsule", project_id="p", user_id="u")
    state = GraphState(job_id=job.id, genome={}, score={"total": 50.0, "components": {}}, status="succeeded")

    ref = await pipeline._capsule_builder(job, source, tmp_path, [], None)(state)

    assert ref.startswith("file://")
    assert list(tmp_path.glob("*.revive"))
