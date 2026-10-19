from __future__ import annotations

import pytest
from revive_api.control_plane import MemoryControlPlane
from revive_api.store import MemoryStore


@pytest.mark.asyncio
async def test_memory_admin_operations_share_state() -> None:
    port = MemoryControlPlane(MemoryStore())
    user = await port.add_user("admin@example.com", "hash", role="admin")
    assert await port.is_maintenance() is False
    await port.set_maintenance(True)
    assert await port.is_maintenance() is True
    await port.append_audit(user.id, "maintenance", {"enabled": False}, {"enabled": True})
    assert port.store.admin_audit[0]["what"] == "maintenance"


@pytest.mark.asyncio
async def test_admin_job_listing_filters_status() -> None:
    port = MemoryControlPlane(MemoryStore())
    user = await port.add_user("admin2@example.com", "hash", role="admin")
    project = await port.add_project(user.id, "https://github.com/acme/admin", "acme/admin")
    job = await port.add_job(project.id, user.id)
    await port.update_job(job.id, status="failed")
    assert [item.id for item in await port.list_admin_jobs("failed")] == [job.id]
    assert await port.list_admin_jobs("running") == []
