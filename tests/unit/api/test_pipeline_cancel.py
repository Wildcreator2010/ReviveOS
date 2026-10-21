"""Cancellation must reach the terminal 'cancelled' state, not 'failed/internal_error'."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from revive_api.store import JobRecord
from revive_api.tasks.pipeline import JobCancelled, execute_job


class Store:
    def __init__(self, job: JobRecord) -> None:
        self.job = job
        self.updates: list[dict[str, Any]] = []

    async def get_job(self, job_id: str) -> JobRecord | None:
        return self.job if job_id == self.job.id else None

    async def update_job(self, job_id: str, **fields: Any) -> None:
        self.updates.append(fields)
        for name, value in fields.items():
            setattr(self.job, name, value)


class Events:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.published.append((job_id, event_type, payload))
        return {"type": event_type, **payload}


class CancellingPort:
    async def ensure_env(self, genome: Any) -> Any:
        raise JobCancelled("job-1")

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_cancellation_is_recorded_as_cancelled(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# demo\n", encoding="utf-8")
    job = JobRecord(id="rev_job_cancel", project_id="project-1", user_id="user-1")
    job.metadata["source_path"] = str(source)
    store = Store(job)
    events = Events()

    result = await execute_job(
        job.id,
        store=store,
        events=events,
        execution_factory=lambda job_id, path: CancellingPort(),
        provider=object(),
    )

    assert result.status == "cancelled"
    assert store.job.status == "cancelled"
    assert events.published[-1][1] == "job.failed"
    assert events.published[-1][2] == {"status": "cancelled", "reason": "user_cancelled"}
