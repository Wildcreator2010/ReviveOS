from __future__ import annotations

import pytest
from revive_api.control_plane import MemoryControlPlane
from revive_api.store import MemoryStore


@pytest.mark.asyncio
async def test_memory_control_plane_exposes_async_resource_operations() -> None:
    adapter = MemoryControlPlane(MemoryStore())
    user = await adapter.add_user("owner@example.com", "hash")
    project = await adapter.add_project(user.id, "https://github.com/acme/repo", "acme/repo")
    assert (await adapter.get_project(project.id)).repo_url == project.repo_url
    assert [item.id for item in await adapter.list_projects(user.id)] == [project.id]

    job = await adapter.add_job(project.id, user.id)
    assert (await adapter.get_job(job.id)).status == "queued"
    assert [item.id for item in await adapter.list_jobs(user.id)] == [job.id]
    assert len(await adapter.active_jobs(user.id)) == 1
    await adapter.update_job(job.id, status="succeeded")
    assert (await adapter.get_job(job.id)).status == "succeeded"
    assert await adapter.jobs_today(user.id) == 1


@pytest.mark.asyncio
async def test_find_api_key_hashes_only_candidates_with_the_same_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MemoryControlPlane(MemoryStore())
    user = await adapter.add_user("keys@example.com", "hash")
    first = await adapter.add_api_key(user.id, "rvk_aaaa", "hash-1")
    await adapter.add_api_key(user.id, "rvk_bbbb", "hash-2")
    checked: list[str] = []

    def fake_verify(value: str, hashed: str) -> bool:
        checked.append(hashed)
        return hashed == "hash-1"

    monkeypatch.setattr("revive_api.security.verify_api_key", fake_verify)
    found = await adapter.find_api_key("rvk_aaaa-secret")

    assert found is not None and found.id == first.id
    assert checked == ["hash-1"], "keys with a different prefix must not reach Argon2"


def test_memory_control_plane_is_not_a_production_adapter() -> None:
    assert MemoryControlPlane().durable is False


def test_postgres_repository_advertises_the_same_durable_seam() -> None:
    from revive_api.db.repository import ControlPlaneRepository

    assert ControlPlaneRepository.durable is True
    for name in ("add_project", "list_projects", "add_job", "list_jobs", "update_job", "soft_delete_project"):
        assert hasattr(ControlPlaneRepository, name)
