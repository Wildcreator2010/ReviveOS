"""T-BE-05 seams that must hold without a broker, a database or a Docker daemon."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from revive_api import celery_app as celery_module
from revive_api import worker
from revive_api.celery_app import TASK_PIPELINE, TASK_SWEEP, create_celery, redis_url
from revive_api.store import MemoryStore
from revive_api.tasks import sweeper
from revive_api.tasks.pipeline import CancellableExecution, JobCancelled, docker_execution_port, sequence_of

LABEL = sweeper.LABEL_KEY


class FakeContainer:
    def __init__(self, container_id: str, job_id: str) -> None:
        self.id = container_id
        self.attrs = {"Config": {"Labels": {LABEL: job_id}}}


class FakeClient:
    def __init__(self, containers: list[FakeContainer]) -> None:
        self._containers = containers
        self.list_calls: list[dict[str, Any]] = []

    @property
    def containers(self) -> Any:
        client = self

        class _Api:
            def list(self, *, all: bool = False, filters: dict[str, Any] | None = None) -> list[FakeContainer]:
                client.list_calls.append({"all": all, "filters": filters or {}})
                return list(client._containers)

        return _Api()


class RecordingSweep:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def __call__(self, client: Any, job_id: str | None = None) -> list[str]:
        self.calls.append(job_id)
        return [
            container.id
            for container in client.containers.list()
            if container.attrs["Config"]["Labels"][LABEL] == job_id
        ]


class FakeStore:
    durable = True

    def __init__(self, jobs: dict[str, Any] | None = None) -> None:
        self.jobs = jobs or {}


class FakeAsyncResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id
        self.called_with: str | None = None

    def delay(self, job_id: str) -> FakeAsyncResult:
        self.called_with = job_id
        return self


def test_celery_keeps_the_worker_red_lines() -> None:
    conf = celery_module.celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_acks_on_failure_or_timeout is False
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_max_tasks_per_child == 10
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_default_queue == "revive"
    assert conf.timezone == "UTC"
    assert conf.beat_schedule["sweep-orphan-sandboxes"] == {"task": TASK_SWEEP, "schedule": 600.0}
    assert conf.include == ["revive_api.tasks.pipeline", "revive_api.tasks.sweeper"]


def test_create_celery_honours_an_explicit_broker_url() -> None:
    app = create_celery("redis://example.invalid:6399/3")
    assert app.conf.broker_url == "redis://example.invalid:6399/3"
    assert app.conf.result_backend == "redis://example.invalid:6399/3"


def test_redis_url_prefers_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert redis_url() == "redis://localhost:6379/0"
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/1")
    assert redis_url() == "redis://cache:6379/1"


def test_pipeline_and_sweep_tasks_are_registered_on_the_app() -> None:
    from revive_api.tasks import pipeline

    assert pipeline.run_resurrection_job.name == TASK_PIPELINE
    assert sweeper.sweep_orphan_sandboxes.name == TASK_SWEEP
    assert TASK_PIPELINE in celery_module.celery_app.tasks
    assert TASK_SWEEP in celery_module.celery_app.tasks


def test_docker_factory_refuses_a_worker_without_a_usable_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    from revive_core.sandbox.executor import SandboxUnavailableError

    monkeypatch.setattr("revive_core.sandbox.port_impl.docker_available", lambda: (False, "docker daemon unreachable"))
    with pytest.raises(SandboxUnavailableError):
        docker_execution_port("job_1", Path("."))


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [(None, 0), ("", 0), ("evt_000000000042", 42), ("not-a-cursor", 0)],
)
def test_sequence_of_parses_only_the_event_cursor(cursor: str | None, expected: int) -> None:
    assert sequence_of(cursor) == expected


class GuardStore:
    def __init__(self, cancel_requested: bool) -> None:
        self.job = type("J", (), {"cancel_requested": cancel_requested})()
        self.runs: list[tuple[str, list[str]]] = []

    async def get_job(self, job_id: str) -> Any:
        return self.job

    async def update_job(self, job_id: str, **fields: Any) -> None:
        return None


class InnerPort:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ensure_env(self, genome: Any) -> str:
        self.calls.append("ensure_env")
        return "handle"

    async def run(self, kind: str, argv: list[str], timeout: float | None = None) -> str:
        self.calls.append(kind)
        return f"{kind}:ok"


async def test_cancellation_guard_aborts_before_the_next_stage() -> None:
    inner = InnerPort()
    guarded = CancellableExecution(inner, GuardStore(True), "job_1")

    with pytest.raises(JobCancelled):
        await guarded.ensure_env(None)
    assert inner.calls == []


async def test_cancellation_guard_lets_a_live_job_through() -> None:
    inner = InnerPort()
    guarded = CancellableExecution(inner, GuardStore(False), "job_1")

    assert await guarded.ensure_env(None) == "handle"
    assert await guarded.run("build", ["python", "-V"], 30) == "build:ok"
    assert inner.calls == ["ensure_env", "build"]


def test_grouped_and_orphan_helpers_are_pure() -> None:
    client = FakeClient([FakeContainer("a", "job-1"), FakeContainer("b", "job-1"), FakeContainer("c", "job-2")])
    grouped = sweeper.containers_by_job(client)

    assert grouped == {"job-1": ["a", "b"], "job-2": ["c"]}
    assert client.list_calls[0]["filters"] == {"label": LABEL}
    assert sweeper.orphan_job_ids(grouped, {"job-1": "succeeded", "job-2": "running"}) == ["job-1"]
    assert sweeper.orphan_job_ids(grouped, {}) == ["job-1", "job-2"]
    assert sweeper.orphan_job_ids(grouped, {"job-1": "running", "job-2": "running"}) == []


async def test_sweeper_removes_terminal_and_unknown_jobs_but_never_live_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        [
            FakeContainer("aaa", "rev_job_live"),
            FakeContainer("bbb", "rev_job_done"),
            FakeContainer("ccc", "rev_job_gone"),
        ]
    )
    recorder = RecordingSweep()
    monkeypatch.setattr(sweeper, "sweep_orphans", recorder)

    class Repo:
        async def get_job(self, job_id: str) -> Any:
            return type("J", (), {"status": "running"})() if job_id == "rev_job_live" else None

    result = await sweeper.sweep(client, Repo())

    assert result["scanned"] == 3
    assert result["orphan_jobs"] == ["rev_job_done", "rev_job_gone"]
    assert sorted(result["removed"]) == ["bbb", "ccc"]
    assert recorder.calls == ["rev_job_done", "rev_job_gone"]


def test_dispatch_falls_back_to_inline_without_a_durable_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVIVE_WORKER__INLINE", raising=False)
    store = MemoryStore()
    project = store.add_project("user_1", "https://github.com/acme/dispatch")
    job = store.add_job(project)

    handled = worker.dispatch_job(store, job.id)

    assert handled.result(timeout=15) is None
    assert store.jobs[job.id].status in {"succeeded", "failed"}
    assert "celery_task_id" not in store.jobs[job.id].metadata


def test_dispatch_hands_a_durable_job_to_celery_and_records_the_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from revive_api.tasks import pipeline

    fake = FakeAsyncResult("task-123")
    monkeypatch.setattr(pipeline, "run_resurrection_job", fake)
    store = FakeStore({"rev_job_1": type("J", (), {"metadata": {}})()})

    result = worker.dispatch_job(store, "rev_job_1")

    assert fake.called_with == "rev_job_1"
    assert result is fake
    assert store.jobs["rev_job_1"].metadata["celery_task_id"] == "task-123"


def test_inline_environment_flag_wins_over_a_durable_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIVE_WORKER__INLINE", "1")
    assert worker.inline_worker_requested(FakeStore()) is True
    monkeypatch.delenv("REVIVE_WORKER__INLINE")
    assert worker.inline_worker_requested(FakeStore()) is False
    assert worker.inline_worker_requested(MemoryStore()) is True


def test_revoke_job_asks_the_broker_to_terminate_and_is_silent_without_a_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    class Control:
        def revoke(self, task_id: str, terminate: bool = False) -> None:
            calls.append((task_id, terminate))

    monkeypatch.setattr(celery_module.celery_app, "control", Control())
    store = FakeStore({"rev_job_1": type("J", (), {"metadata": {"celery_task_id": "task-9"}})()})

    assert worker.revoke_job(store, "rev_job_1") == "task-9"
    assert calls == [("task-9", True)]
    assert worker.revoke_job(store, "rev_job_missing") == ""
    assert len(calls) == 1
