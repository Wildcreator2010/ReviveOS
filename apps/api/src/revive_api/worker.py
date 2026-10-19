"""Inline development executor and the job dispatch seam (T-BE-05 support).

`run_job` is the **inline** executor used by tests and by `dev` when no durable
store is configured: it publishes the contracted event sequence through the
in-memory store so the whole control plane stays exercisable without Redis,
Celery or Docker. It is not the production path -- the production path is
`revive_api.tasks.pipeline.run_resurrection_job`, which runs in a Celery worker
against PostgreSQL + Redis + the Docker sandbox.

`dispatch_job` picks between them: a store that is not durable can only run
inline, and `REVIVE_WORKER__INLINE=1` forces inline even for durable stores.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import tarfile
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from .store import MemoryStore


def _pause() -> None:
    time.sleep(0.05)


def _capsule_content(project_url: str, job_id: str) -> tuple[dict[str, Any], bytes]:
    manifest: dict[str, Any] = {
        "format": "revive/v1",
        "source": {"repo": project_url, "commit": "dev0000"},
        "genome_ref": f"genome://{job_id}",
        "behavior": {"compatibility": "not_measured"},
        "score": {"total": 0, "components": {}},
        "patches": [],
        "sbom_digest": f"dev-{job_id}",
        "provenance": {"evidence": [], "llm_traces": []},
        "status": "partial",
    }
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return manifest, stream.getvalue()


def run_job(store: MemoryStore, job_id: str) -> None:
    """Run a deterministic development job and publish every major transition."""

    job = store.jobs.get(job_id)
    if job is None or job.status in {"cancelled", "succeeded", "failed"}:
        return
    project = store.projects.get(job.project_id)
    if project is None:
        job.status = "failed"
        store.event_bus.publish(job.id, "job.failed", {"status": "failed", "reason": "project_missing"})
        return

    def emit(event_type: str, payload: dict[str, Any] | None = None) -> None:
        store.event_bus.publish(job.id, event_type, payload or {})

    try:
        job.status = "running"
        project.status = "running"
        emit("archaeology.started", {"status": "running"})
        _pause()
        if job.cancel_requested:
            raise asyncio.CancelledError
        emit("archaeology.evidence", {"count": 1, "source": project.repo_url, "warnings": []})
        _pause()
        job.metadata["genome"] = {
            "python": {"version": "unknown", "confidence": 0.0, "evidence": []},
            "os": {"confidence": 0.0, "evidence": []},
            "dependencies": [],
            "cuda": {"confidence": 0.0, "evidence": []},
            "system_libs": [],
            "overall_confidence": 0.0,
        }
        emit("env.inferred", {"confidence": 0.0})
        emit("sandbox.created", {"backend": "development"})
        _pause()
        job.metadata["builds"] = [{"stage": "build", "ok": True, "attempt": 1}]
        emit("build.attempt", {"attempt": 1, "ok": True})
        _pause()
        job.metadata["behavior"] = {"compatibility": None, "degraded": True}
        emit("test.attempt", {"ok": True, "tests_absent": True})
        emit("score.computed", {"total": 0, "status": "partial"})
        manifest, content = _capsule_content(project.repo_url, job.id)
        capsule = store.add_capsule(project, manifest, content)
        job.metadata["score"] = {"total": 0, "status": "partial"}
        job.metadata["capsule_id"] = capsule.id
        emit("capsule.created", {"capsule_id": capsule.id})
        job.status = "succeeded"
        project.status = "succeeded"
        emit("job.succeeded", {"status": "succeeded", "capsule_id": capsule.id})
    except asyncio.CancelledError:
        job.cancel_requested = True
        job.status = "cancelled"
        project.status = "cancelled"
        emit("job.failed", {"status": "cancelled", "reason": "cancelled"})
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        job.status = "failed"
        project.status = "failed"
        emit("job.failed", {"status": "failed", "reason": str(exc)[:200]})


_executor = ThreadPoolExecutor(max_workers=4)


def schedule_job(store: MemoryStore, job_id: str) -> Future[None]:
    return _executor.submit(run_job, store, job_id)


def inline_worker_requested(store: Any) -> bool:
    """True unless the store is durable and nobody forced the inline executor."""

    if os.getenv("REVIVE_WORKER__INLINE", "").strip() == "1":
        return True
    return not bool(getattr(store, "durable", False))


def dispatch_job(store: Any, job_id: str) -> Any:
    """Queue the job on the inline executor, or hand it to the Celery worker."""

    if inline_worker_requested(store):
        return schedule_job(store, job_id)

    from .tasks.pipeline import run_resurrection_job

    result = run_resurrection_job.delay(job_id)
    job = store.jobs.get(job_id) if hasattr(store, "jobs") else None
    if job is not None:
        job.metadata["celery_task_id"] = str(result.id)
    return result


def revoke_job(store: Any, job_id: str) -> str:
    """Ask the broker to terminate the in-flight task; the stage guard is the graceful path."""

    job = store.jobs.get(job_id) if hasattr(store, "jobs") else None
    task_id = str(job.metadata.get("celery_task_id") or "") if job is not None else ""
    if not task_id:
        return ""
    from .celery_app import celery_app

    celery_app.control.revoke(task_id, terminate=True)
    return task_id


__all__ = ["dispatch_job", "inline_worker_requested", "revoke_job", "run_job", "schedule_job"]
