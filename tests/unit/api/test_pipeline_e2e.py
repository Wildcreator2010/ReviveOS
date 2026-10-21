"""End-to-end (no Docker): the worker path must produce a real capsule event."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from revive_api.store import JobRecord
from revive_api.tasks.pipeline import execute_job
from revive_core.sandbox.executor import RunResult


class Store:
    def __init__(self, job: JobRecord) -> None:
        self.job = job
        self.metadata: dict[str, Any] = {}

    async def get_job(self, job_id: str) -> JobRecord | None:
        return self.job if job_id == self.job.id else None

    async def update_job(self, job_id: str, **fields: Any) -> None:
        for name, value in fields.items():
            setattr(self.job, name, value)

    async def set_job_metadata(self, job_id: str, **values: Any) -> None:
        self.metadata.update(values)


class Events:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.published.append({"type": event_type, "payload": payload, "job_id": job_id})
        return self.published[-1]


class Port:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ensure_env(self, genome: Any) -> Any:
        return SimpleNamespace(port=self)

    async def run(self, kind: str, argv: list[str], timeout: float) -> RunResult:
        self.calls.append(kind)
        return RunResult(kind=kind, argv=list(argv), exit_code=0, backend="fake")

    async def apply_patch(self, diff: str) -> Any:
        return {"ok": True}

    async def snapshot_ws(self) -> str:
        return "snap"

    async def restore_ws(self, token: Any) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_execute_job_builds_and_reports_a_real_capsule(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "README.md").write_text("# demo\n", encoding="utf-8")
    job = JobRecord(id="rev_job_e2e", project_id="project-e2e", user_id="user-e2e")
    job.metadata["source_path"] = str(source)
    store = Store(job)
    events = Events()
    port = Port()

    result = await execute_job(
        job.id,
        store=store,
        events=events,
        execution_factory=lambda job_id, path: port,
        provider=object(),
        work_root=tmp_path / "work",
    )

    assert result.status == "succeeded"
    capsule_events = [event for event in events.published if event["type"] == "capsule.created"]
    assert len(capsule_events) == 1
    ref = capsule_events[0]["payload"]["capsule_ref"]
    assert ref.startswith("file://")
    assert (tmp_path / "work" / f"{job.id}.revive").is_file()
    assert port.calls == ["build", "test"]
