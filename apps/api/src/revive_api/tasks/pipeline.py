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
import base64
import hashlib
import json
import os
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
import structlog
from revive_agents.budget import BudgetedProvider, JobBudget
from revive_agents.graph import GraphState, build_graph
from revive_agents.llm import from_config, from_settings
from revive_agents.llm.base import Usage
from revive_agents.nodes import repair as repair_node
from revive_agents.nodes.repairer import workspace_manifest
from revive_agents.ports import ExecutionCancelled
from revive_core.archaeology import extract_evidence, fetch_repo, infer_genome
from revive_core.behavior.capture import (
    BehaviorPlan,
    CaseFingerprint,
    CaseSpec,
    Fingerprint,
    capture,
    select_baseline,
)
from revive_core.behavior.compare import compare
from revive_core.capsule.builder import RunState, build_capsule, verify_capsule_structure
from revive_core.gitutil import run_git
from revive_core.sandbox.dockerfile_template import render_dockerfile
from revive_core.sandbox.image_matrix import Unsupported, plan_image

from ..celery_app import TASK_PIPELINE, celery_app
from ..event_bus import AgentEventPort, EventPublisher
from ..secrets import decrypt_secret
from ..store import JobRecord

log = structlog.get_logger(__name__)

TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled"})
DEFAULT_STAGE_TIMEOUT = 300.0


class JobCancelled(ExecutionCancelled):
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
    capsule_uploader: CapsuleUploader | None = None,
) -> PipelineResult:
    """Run one job to a terminal state; returns without touching a finished job."""

    job = await store.get_job(job_id)
    if job is None:
        return PipelineResult(job_id=job_id, status="missing", skipped="unknown_job")
    if job.status in TERMINAL_JOB_STATES:
        return PipelineResult(job_id=job_id, status=job.status, skipped="already_terminal")

    await store.update_job(job_id, status="running")

    pipeline_config = dict(job.metadata.get("pipeline") or {})
    stage_timeout = float(pipeline_config.get("timeout_seconds") or timeout)
    budget_usd = pipeline_config.get("budget_usd")

    port: Any = None
    published = 0
    try:
        source = await _materialise_source(job, work_root)
        genome, evidence = _genome_document(source)
        llm = provider if provider is not None else await _configured_provider(store)
        if llm is None:
            llm = from_config()
        budget = JobBudget(float(budget_usd), job_id=job_id) if budget_usd else JobBudget(job_id=job_id)
        llm = BudgetedProvider(llm, budget)
        usage_recorder = _usage_recorder(store, job)
        if usage_recorder is not None:
            llm = RecordingProvider(llm, usage_recorder)
        port = execution_factory(job_id, source)
        project = {"id": job.project_id, **pipeline_config}
        project.setdefault("workspace_manifest", workspace_manifest(source))
        tests_dir = source / "tests" if (source / "tests").is_dir() else source / "test"
        if not tests_dir.is_dir() or not any(tests_dir.iterdir()):
            project["tests_absent"] = True
            project.setdefault("test_argv", ["python", "-c", "print('no tests collected')"])
        graph = build_graph(
            {
                "execution": CancellableExecution(port, store, job_id),
                "events": AgentEventPort(events),
                "provider": llm,
                "repair": repair_node,
                "behavior": _behavior_runner(source),
                "capsule": _capsule_builder(job, source, work_root, evidence, capsule_uploader),
                "timeout": stage_timeout,
            }
        )
        state = await graph.ainvoke(
            GraphState(
                job_id=job_id,
                project=project,
                genome=genome,
                behavior_plan=_behavior_plan(source),
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
    repo_url = str(job.metadata.get("repo_url") or "").strip()
    if not repo_url:
        raise ValueError(f"job {job.id} has no repo_url in metadata; cannot materialise a source tree")
    root = work_root or Path.cwd() / ".revive-tmp"
    destination = root / f"revive-source-{job.id}"
    if destination.exists() and any(destination.iterdir()):
        return destination
    mirror = fetch_repo(repo_url, destination)
    return mirror.path


_PACKAGE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _detect_package(source: Path) -> str | None:
    for base in (source / "src", source):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if (
                child.is_dir()
                and _PACKAGE_RE.match(child.name)
                and (child / "__init__.py").is_file()
                and child.name not in {"tests", "test", "docs", "examples"}
            ):
                return child.name
    return None


def _behavior_plan(source: Path) -> BehaviorPlan:
    cases: list[CaseSpec] = []
    if (source / "tests").is_dir() or (source / "test").is_dir():
        cases.append(CaseSpec(id="pytest", argv=["python", "-m", "pytest", "-q"]))
    package = _detect_package(source)
    if package:
        cases.append(CaseSpec(id="import", argv=["python", "-c", f"import {package}"]))
    return BehaviorPlan(cases=cases, plan_ref="tests/behavior-plan.json")


def _repo_expected_baseline(source: Path, plan: BehaviorPlan) -> Fingerprint | None:
    expected = source / "tests" / "expected"
    if not expected.is_dir():
        return None
    cases: list[CaseFingerprint] = []
    for case in plan.cases:
        candidate = expected / f"{case.id}.txt"
        if not candidate.is_file():
            return None
        payload = candidate.read_text(encoding="utf-8", errors="replace")
        cases.append(
            CaseFingerprint(
                id=case.id,
                exit_code=0,
                stdout_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                argv=list(case.argv),
            )
        )
    return Fingerprint(
        plan_ref=plan.plan_ref,
        captured_at=datetime.now(UTC).isoformat(),
        cases=cases,
        baseline_source={"priority": 1, "kind": "repo_expected_outputs", "reference": "tests/expected/"},
    )


def _behavior_runner(source: Path) -> Callable[[Any, Any], Awaitable[dict[str, Any]]]:
    async def run(handle: Any, plan: Any) -> dict[str, Any]:
        if handle is None:
            return {"fingerprint": None, "compatibility": None, "matched": False, "cases": 0}
        behavior_plan = plan if isinstance(plan, BehaviorPlan) else BehaviorPlan.from_mapping(plan or {})
        if not behavior_plan.cases:
            return {"fingerprint": None, "compatibility": None, "matched": False, "cases": 0}
        fingerprint = await capture(handle, behavior_plan)
        choice = select_baseline(repo_expected=_repo_expected_baseline(source, behavior_plan))
        result = compare(choice.fingerprint, fingerprint)
        return {
            "fingerprint": fingerprint.to_dict(),
            "compatibility": result.compatibility,
            "matched": result.compatibility == 1.0,
            "cases": len(fingerprint.cases),
        }

    return run


def _git_head(source: Path) -> str:
    try:
        top = run_git(["-C", str(source), "rev-parse", "--show-toplevel"], check=False)
        toplevel = (top.stdout or "").strip()
        if top.returncode != 0 or not toplevel or Path(toplevel).resolve() != source.resolve():
            return "unknown"
        result = run_git(["-C", str(source), "rev-parse", "HEAD"], check=False)
    except Exception:
        return "unknown"
    value = (result.stdout or "").strip()
    return value if result.returncode == 0 and len(value) >= 7 else "unknown"


_DEPENDENCY_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "uv.lock",
)


def _dependencies_lock(source: Path) -> str:
    chunks: list[str] = []
    total = 0
    for name in _DEPENDENCY_FILES:
        path = source / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if total + len(text) > 1_000_000:
            break
        chunks.append(f"# {name}\n{text}\n")
        total += len(text)
    return "\n".join(chunks)


def _capsule_dockerfile(genome: Any) -> str:
    try:
        plan = plan_image(genome)
        if isinstance(plan, Unsupported):
            return f"# unsupported environment: {plan.reason}\n"
        return render_dockerfile(plan)
    except Exception as exc:  # pragma: no cover - template errors are environment-specific
        return f"# dockerfile generation failed: {type(exc).__name__}\n"


def _evidence_refs(items: Sequence[Any]) -> list[str]:
    refs: list[str] = []
    for item in items:
        ref = getattr(item, "ref_string", None)
        refs.append(str(ref()) if callable(ref) else str(getattr(item, "reference", item)))
    return refs


CapsuleUploader = Callable[[str, Path, dict[str, Any], str], Awaitable[str]]


def _capsule_builder(
    job: JobRecord,
    source: Path,
    work_root: Path | None,
    evidence: Sequence[Any],
    uploader: CapsuleUploader | None,
) -> Callable[[GraphState], Awaitable[str]]:
    async def build(state: GraphState) -> str:
        plan = state.behavior_plan
        behavior_plan = plan.to_dict() if hasattr(plan, "to_dict") else _plain(plan) or {}
        patch_entries: list[tuple[str, str]] = []
        for index, patch in enumerate(state.patches or [], start=1):
            data = _plain(patch) if not isinstance(patch, dict) else dict(patch)
            diff = str(data.get("diff", ""))
            if not diff:
                continue
            names = data.get("touched_files") or []
            name = str(names[0]) if names else f"patches/{index}.diff"
            patch_entries.append((name, diff))
        run_state = RunState(
            job_id=job.id,
            source_repo=str(job.metadata.get("repo_url") or source.resolve().as_uri()),
            source_commit=_git_head(source),
            genome=_plain(state.genome) or {},
            dockerfile=_capsule_dockerfile(state.genome),
            score=_plain(state.score) or {},
            dependencies_lock=_dependencies_lock(source),
            patches=patch_entries,
            behavior_plan=behavior_plan,
            fingerprints=_plain(state.fingerprints) if state.fingerprints is not None else None,
            behavior_compatibility=state.behavior_compatibility,
            status="alive" if state.status == "succeeded" and state.behavior_compatibility == 1.0 else "partial",
            provenance={"mode": "worker", "project_id": job.project_id},
            evidence=_evidence_refs(evidence),
            created_at=datetime.now(UTC).isoformat(),
            source_tree=source,
        )
        directory = work_root or Path.cwd() / ".revive-tmp"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{job.id}.revive"
        path = await asyncio.to_thread(build_capsule, run_state, destination)
        report = await asyncio.to_thread(verify_capsule_structure, path)
        manifest = report.get("manifest")
        if not report.get("ok") or not isinstance(manifest, dict):
            raise RuntimeError(f"capsule self-verification failed: {report.get('errors') or report}")
        digest = hashlib.sha256(await asyncio.to_thread(path.read_bytes)).hexdigest()
        if uploader is None:
            return path.resolve().as_uri()
        capsule_id = await uploader(job.id, path, manifest, digest)
        return f"capsule://{capsule_id}"

    return build


async def upload_capsule(
    api_url: str,
    worker_token: str,
    job_id: str,
    path: Path,
    manifest: dict[str, Any],
    sha256: str,
) -> str:
    content = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode("ascii")
    async with httpx.AsyncClient(trust_env=False, timeout=180.0) as client:
        response = await client.post(
            f"{api_url.rstrip('/')}/jobs/{job_id}/capsule",
            headers={"X-Worker-Token": worker_token},
            json={"content": content, "sha256": sha256, "manifest": manifest},
        )
        response.raise_for_status()
        return str(response.json()["id"])


class RecordingProvider:
    """Persist provider-reported usage after each successful LLM call."""

    def __init__(self, provider: Any, recorder: Callable[[Any, str, str, Usage], Awaitable[None]]) -> None:
        self.provider = provider
        self.recorder = recorder

    async def complete(self, messages: Any, **kwargs: Any) -> Any:
        completion = await self.provider.complete(messages, **kwargs)
        target = getattr(self.provider, "provider", self.provider)
        name = str(getattr(target, "name", "") or getattr(target, "provider_name", "") or type(target).__name__)
        model = str(getattr(target, "model", "") or "")
        await self.recorder(name, model, str(kwargs.get("node", "")), Usage.coerce(getattr(completion, "usage", None)))
        return completion


async def _configured_provider(store: JobStore) -> Any | None:
    repository = getattr(store, "repository", None)
    if repository is None or not hasattr(repository, "get_runtime_setting"):
        return None
    settings = await repository.get_runtime_setting("llm")
    if not settings or not settings.get("provider"):
        return None
    runtime = dict(settings)
    encrypted = str(runtime.get("api_key_enc") or "")
    if encrypted:
        runtime["api_key"] = decrypt_secret(encrypted)
    return from_settings(runtime)


def _usage_recorder(store: JobStore, job: JobRecord) -> Callable[[str, str, str, Usage], Awaitable[None]] | None:
    repository = getattr(store, "repository", None)
    if repository is None or not hasattr(repository, "record_llm_call"):
        return None

    async def record(provider: str, model: str, node: str, usage: Usage) -> None:
        try:
            await repository.record_llm_call(
                provider,
                model,
                {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cost_usd_estimate": usage.cost_usd_estimate,
                },
                usage.cost_usd_estimate,
                job_id=job.id,
                user_id=job.user_id,
                node=node,
            )
            await repository.commit()
        except Exception:  # telemetry must never fail the job
            log.exception("pipeline.llm_cost_record_failed", job_id=job.id)

    return record


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
        behavior={"compatibility": state.behavior_compatibility, "captured": bool(state.fingerprints)},
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
    api_url = os.getenv("REVIVE_API_URL", "").strip() or "http://127.0.0.1:8000"

    async def uploader(job_id: str, path: Path, manifest: dict[str, Any], sha256: str) -> str:
        return await upload_capsule(api_url, config.worker_token, job_id, path, manifest, sha256)

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
                capsule_uploader=uploader,
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
