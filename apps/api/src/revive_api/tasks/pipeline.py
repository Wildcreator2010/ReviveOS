"""The resurrection pipeline as a Celery task (T-BE-05).

`execute_job` is the process-independent core: it takes a job-store seam, an event
publisher and an execution-port factory, so the same code runs inside a Celery
worker (PostgreSQL + Redis + Docker) and inside an integration test (throwaway
schema + real Redis + the local sandbox substitute).  `run_resurrection_job` is the
thin Celery wrapper that opens those real collaborators.

Rules honoured here: a job already in a terminal state is never re-run, the only
place user code executes is the sandbox port, and cancellation is checked before
every stage instead of relying on `revoke(terminate)` alone.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import structlog
from revive_agents.graph import GraphState, build_graph
from revive_agents.llm import from_config
from revive_core.archaeology import extract_evidence, fetch_repo, infer_genome

from ..celery_app import TASK_PIPELINE, celery_app
from ..event_bus import AgentEventPort, EventPublisher
from ..store import JobRecord

log = structlog.get_logger(__name__)

TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled"})
DEFAULT_STAGE_TIMEOUT = 300.0


class JobCancelled(RuntimeError):
    """Raised by the cancellation guard before a stage starts."""


class JobStore(Protocol):
    async def get_job(self, job_id: str) -> JobRecord | None: ...

    async def update_job(self, job_id: str, **fields: Any) -> None: ...


class ExecutionFactory(Protocol):
    def __call__(self, job_id: str, source: Path) -> Any: ...


@dataclass
class PipelineResult:
    job_id: str
    status: str
    skipped: str = ""
    events: int = 0
    failure_reason: str = ""
    score: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "skipped": self.skipped,
            "events": self.events,
            "failure_reason": self.failure_reason,
            "score": self.score,
        }


class CancellableExecution:
    """Wraps an execution port and aborts the moment the job asks to be cancelled."""

    def __init__(self, inner: Any, store: JobStore, job_id: str) -> None:
        self.inner = inner
        self.store = store
        self.job_id = job_id

    async def _guard(self) -> None:
        job = await self.store.get_job(self.job_id)
        if job is not None and job.cancel_requested:
            raise JobCancelled(self.job_id)

    async def ensure_env(self, genome: Any) -> Any:
        await self._guard()
        return await self.inner.ensure_env(genome)

    async def run(self, kind: str, argv: list[str], timeout: float | None = None) -> Any:
        await self._guard()
        return await self.inner.run(kind, argv, timeout)

    async def apply_patch(self, diff: str) -> Any:
        await self._guard()
        return await self.inner.apply_patch(diff)

    async def snapshot_ws(self) -> Any:
        return await self.inner.snapshot_ws()

    async def restore_ws(self, token: Any) -> Any:
        return await self.inner.restore_ws(token)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _genome_document(source: Path) -> tuple[dict[str, Any], list[Any]]:
    evidence = extract_evidence(source)
    genome = infer_genome(evidence)
    return json.loads(genome.model_dump_json()), list(evidence)


async def execute_job(
    job_id: str,
    *,
    store: JobStore,
    events: EventPublisher,
    execution_factory: ExecutionFactory,
    provider: Any = None,
    work_root: Path | None = None,
    timeout: float = DEFAULT_STAGE_TIMEOUT,
) -> PipelineResult:
    """Run one job to a terminal state; returns without touching a finished job."""

    job = await store.get_job(job_id)
    if job is None:
        return PipelineResult(job_id=job_id, status="missing", skipped="unknown_job")
    if job.status in TERMINAL_JOB_STATES:
        return PipelineResult(job_id=job_id, status=job.status, skipped="already_terminal")

    await store.update_job(job_id, status="running")

    port: Any = None
    published = 0
    try:
        source = await _materialise_source(job, work_root)
        genome, evidence = _genome_document(source)
        llm = provider if provider is not None else from_config()
        port = execution_factory(job_id, source)
        graph = build_graph(
            {
                "execution": CancellableExecution(port, store, job_id),
                "events": AgentEventPort(events),
                "provider": llm,
                "timeout": timeout,
            }
        )
        state = await graph.ainvoke(
            GraphState(
                job_id=job_id,
                project={"id": job.project_id, **(job.metadata.get("pipeline", {}) or {})},
                genome=genome,
            )
        )
        published = len(graph.emitted)
        await _record_artifacts(store, job_id, genome, graph.emitted, state)
        await _persist_tables(store, job, genome, evidence, graph.emitted, state)

        if state.status == "succeeded":
            await store.update_job(job_id, status="succeeded")
            return PipelineResult(job_id=job_id, status="succeeded", events=published, score=dict(state.score or {}))

        reason = str(state.failure_reason or "pipeline_failed")
        await events.publish(job_id, "job.failed", {"status": "failed", "reason": reason[:200]})
        await store.update_job(job_id, status="failed")
        return PipelineResult(job_id=job_id, status="failed", events=published + 1, failure_reason=reason)
    except JobCancelled:
        await events.publish(job_id, "job.failed", {"status": "cancelled", "reason": "user_cancelled"})
        await store.update_job(job_id, status="cancelled")
        return PipelineResult(job_id=job_id, status="cancelled", failure_reason="user_cancelled")
    except Exception as exc:  # noqa: BLE001 - the worker boundary must always reach a terminal state
        log.error("pipeline.crashed", job_id=job_id, error=f"{type(exc).__name__}: {exc}")
        await events.publish(job_id, "job.failed", {"status": "failed", "reason": "worker_error"})
        await store.update_job(job_id, status="failed")
        return PipelineResult(job_id=job_id, status="failed", failure_reason=f"{type(exc).__name__}: {exc}")
    finally:
        close = getattr(port, "close", None)
        if callable(close):
            await close()


async def _materialise_source(job: JobRecord, work_root: Path | None) -> Path:
    """Use a pre-staged local tree when present, otherwise clone the repository."""

    staged = job.metadata.get("source_path")
    if staged:
        path = Path(str(staged))
        if not path.is_dir():
            raise FileNotFoundError(f"staged source path is missing: {path}")
        return path
    root = work_root or Path.cwd() / ".revive-tmp"
    destination = root / f"revive-source-{job.id}"
    if destination.exists() and any(destination.iterdir()):
        return destination
    mirror = fetch_repo(str(job.metadata.get("repo_url", "")), destination)
    return mirror.path


async def _record_artifacts(
    store: JobStore,
    job_id: str,
    genome: dict[str, Any],
    emitted: list[dict[str, Any]],
    state: GraphState,
) -> None:
    set_metadata = getattr(store, "set_job_metadata", None)
    if not callable(set_metadata):
        return
    builds = [
        {"stage": event["type"], "attempt": event["payload"].get("attempt"), **event["payload"]}
        for event in emitted
        if str(event["type"]).startswith("build.")
    ]
    await set_metadata(
        job_id,
        genome=genome,
        builds=builds,
        patches=[{"index": index, **_plain(patch)} for index, patch in enumerate(state.patches, start=1)],
        behavior={"compatibility": None, "captured": bool(state.fingerprints)},
        score=_plain(state.score) if state.score else {},
        events_recorded=len(emitted),
    )


async def _persist_tables(
    store: JobStore,
    job: JobRecord,
    genome: dict[str, Any],
    evidence: list[Any],
    emitted: list[dict[str, Any]],
    state: GraphState,
) -> None:
    """Write the durable artifact rows when the store exposes a repository.

    The inline (`MemoryStore`) path keeps only job metadata, so it returns here;
    that is why `dispatch_job` treats a non-durable store as test-only.
    """

    repository = getattr(store, "repository", None)
    if repository is None or not hasattr(repository, "add_genome"):
        return

    from ..services.evidence_service import EmbedConfig, embed_excerpt, persist_evidence, persist_job_artifacts

    config = EmbedConfig.from_env()

    async def embed(text: str) -> list[float] | None:
        return await embed_excerpt(text, config)

    build_ok = any(str(event.get("type")) == "test.attempt" for event in emitted)
    written = await persist_evidence(
        repository,
        project_id=job.project_id,
        job_id=job.id,
        genome=genome,
        items=evidence,
        embedder=embed,
    )
    counts = await persist_job_artifacts(
        repository,
        project_id=job.project_id,
        job_id=job.id,
        genome=genome,
        emitted=emitted,
        state=state,
        build_ok=build_ok,
    )
    log.info("pipeline.artifacts_persisted", job_id=job.id, evidence=written, **counts)
    commit = getattr(repository, "commit", None)
    if callable(commit):
        await commit()


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _plain(model_dump(mode="json"))
    return str(value)


# -- production wiring ---------------------------------------------------


def sequence_of(cursor: str | None) -> int:
    """`evt_000000000042` -> 42; anything unreadable restarts the replay at zero."""

    if not cursor:
        return 0
    digits = str(cursor).rsplit("_", 1)[-1]
    try:
        return int(digits)
    except ValueError:
        return 0


class PostgresEventSink:
    """`job_events` writer/reader behind the bus's EventSink protocol."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    async def add_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = await self.repository.add_event(job_id, event_type, payload)
        await self.repository.commit()
        return record.as_dict()

    async def history(self, job_id: str, after_id: str | None) -> list[dict[str, Any]]:
        records = await self.repository.events_for_job(job_id, sequence_of(after_id))
        return [record.as_dict() for record in records]


class PostgresJobStore:
    """Job seam that commits, so a cancellation written by the API becomes visible.

    A plain session would keep reusing one snapshot for the whole job and the
    per-stage cancel guard would never see the new `cancel_requested` flag.
    """

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    async def get_job(self, job_id: str) -> JobRecord | None:
        await self.repository.commit()
        return await self.repository.get_job(job_id)

    async def update_job(self, job_id: str, **fields: Any) -> None:
        await self.repository.update_job(job_id, **fields)
        await self.repository.commit()

    async def set_job_metadata(self, job_id: str, **values: Any) -> None:
        await self.repository.set_job_metadata(job_id, **values)
        await self.repository.commit()


def docker_execution_port(job_id: str, source: Path) -> Any:
    """The only execution backend allowed in a worker: a hardened Docker sandbox."""

    from revive_core.sandbox.executor import SandboxUnavailableError
    from revive_core.sandbox.port_impl import DockerExecutionPort, docker_available

    usable, reason = docker_available()
    if not usable:
        raise SandboxUnavailableError(f"no sandbox backend available in this worker: {reason}")
    return DockerExecutionPort(workspace=source, job_id=job_id)


async def run_with_production_ports(
    job_id: str, *, execution_factory: ExecutionFactory = docker_execution_port
) -> dict[str, Any]:
    """Open PostgreSQL + Redis, run one job to a terminal state, then close both."""

    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ..celery_app import redis_url
    from ..config import Config
    from ..db.repository import ControlPlaneRepository
    from ..event_bus import RedisEventBus

    config = Config.from_env()
    if not config.database_url:
        raise RuntimeError("DATABASE_URL is required to run the pipeline worker")

    engine = create_async_engine(config.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = aioredis.from_url(redis_url(config))
    try:
        async with session_factory() as session:
            repository = ControlPlaneRepository(session)
            bus = RedisEventBus(PostgresEventSink(repository), client)
            result = await execute_job(
                job_id,
                store=PostgresJobStore(repository),
                events=bus,
                execution_factory=execution_factory,
            )
            await session.commit()
        return result.as_dict()
    finally:
        await client.aclose()
        await engine.dispose()


@celery_app.task(bind=True, name=TASK_PIPELINE)
def run_resurrection_job(self: Any, job_id: str) -> dict[str, Any]:
    """Celery entry point: one job per task, idempotent because the state decides."""

    return asyncio.run(run_with_production_ports(job_id))


__all__ = [
    "CancellableExecution",
    "DEFAULT_STAGE_TIMEOUT",
    "ExecutionFactory",
    "JobCancelled",
    "JobStore",
    "PipelineResult",
    "PostgresEventSink",
    "PostgresJobStore",
    "docker_execution_port",
    "execute_job",
    "run_resurrection_job",
    "run_with_production_ports",
    "sequence_of",
]
