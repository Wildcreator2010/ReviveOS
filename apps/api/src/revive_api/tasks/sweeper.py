"""Orphan sandbox sweeper (T-BE-05).

Beat runs `sweep_orphan_sandboxes` every 10 minutes. A container is only removed
when its `revive.job_id` label points at a job that has already reached a terminal
state or no longer exists -- a running job's sandbox is never touched.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import structlog
from revive_core.sandbox.executor import LABEL_KEY
from revive_core.sandbox.port_impl import sweep_orphans

from ..celery_app import TASK_SWEEP, celery_app
from .pipeline import TERMINAL_JOB_STATES

log = structlog.get_logger(__name__)


class JobLookup(Protocol):
    async def get_job(self, job_id: str) -> Any: ...


def containers_by_job(client: Any) -> dict[str, list[str]]:
    """Group every revive-labelled container under its job id."""

    grouped: dict[str, list[str]] = {}
    for container in client.containers.list(all=True, filters={"label": LABEL_KEY}):
        labels = (container.attrs.get("Config", {}) or {}).get("Labels", {}) or {}
        grouped.setdefault(str(labels.get(LABEL_KEY, "")), []).append(str(container.id))
    return grouped


def orphan_job_ids(grouped: dict[str, list[str]], statuses: dict[str, str]) -> list[str]:
    """Terminal or unknown jobs own the orphan containers; live jobs do not."""

    orphans: list[str] = []
    for job_id in grouped:
        status = statuses.get(job_id, "missing")
        if status in TERMINAL_JOB_STATES or status == "missing":
            orphans.append(job_id)
    return sorted(orphans)


async def collect_statuses(store: JobLookup, job_ids: list[str]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for job_id in job_ids:
        job = await store.get_job(job_id)
        if job is not None:
            statuses[job_id] = str(job.status)
    return statuses


async def sweep(client: Any, store: JobLookup) -> dict[str, Any]:
    grouped = containers_by_job(client)
    statuses = await collect_statuses(store, sorted(grouped))
    orphans = orphan_job_ids(grouped, statuses)

    removed: list[str] = []
    for job_id in orphans:
        removed.extend(sweep_orphans(client, job_id))
        log.info("sweeper.removed", job_id=job_id, status=statuses.get(job_id, "missing"))
    return {"scanned": sum(len(ids) for ids in grouped.values()), "orphan_jobs": orphans, "removed": removed}


async def _run() -> dict[str, Any]:
    import docker
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ..config import Config
    from ..db.repository import ControlPlaneRepository

    config = Config.from_env()
    if not config.database_url:
        raise RuntimeError("DATABASE_URL is required to sweep orphan sandboxes")

    client = docker.from_env()
    engine = create_async_engine(config.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            return await sweep(client, ControlPlaneRepository(session))
    finally:
        await engine.dispose()
        client.close()


@celery_app.task(name=TASK_SWEEP)
def sweep_orphan_sandboxes() -> dict[str, Any]:
    return asyncio.run(_run())


__all__ = [
    "JobLookup",
    "collect_statuses",
    "containers_by_job",
    "orphan_job_ids",
    "sweep",
    "sweep_orphan_sandboxes",
]
