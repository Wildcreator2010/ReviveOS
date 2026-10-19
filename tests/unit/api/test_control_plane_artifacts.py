from __future__ import annotations

import pytest
from revive_api.control_plane import MemoryControlPlane
from revive_api.store import MemoryStore


@pytest.mark.asyncio
async def test_evidence_pagination_and_latest_job_use_control_plane_port() -> None:
    port = MemoryControlPlane(MemoryStore())
    user = await port.add_user("artifact@example.com", "hash")
    project = await port.add_project(user.id, "https://github.com/acme/old", "acme/old")
    first = await port.add_evidence(project.id, "manifest_file", "requirements.txt", {"version": 1}, 0.9)
    second = await port.add_evidence(project.id, "ci_config", ".github/workflows/test.yml", {}, 0.2)
    assert [item.id for item in await port.list_evidence(project.id, limit=1)] == [first.id]
    assert [item.id for item in await port.list_evidence(project.id, "ci_config")] == [second.id]

    older = await port.add_job(project.id, user.id)
    newer = await port.add_job(project.id, user.id)
    assert (await port.latest_job(project.id)).id == newer.id
    assert (await port.get_job(older.id)).status == "queued"
