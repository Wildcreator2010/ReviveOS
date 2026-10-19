"""Celery application for the resurrection pipeline worker (T-BE-05).

Only one process type runs user code paths, and it is the worker: the API never
executes repository code in-process (global red line 3).  The broker/result store
is the same Redis the event bus uses; both come from `REDIS_URL` and nothing is
hard-coded except the documented dev default.
"""

from __future__ import annotations

import os

from celery import Celery

from .config import Config

DEFAULT_QUEUE = "revive"
SWEEP_INTERVAL_SECONDS = 600.0

TASK_PIPELINE = "revive.run_resurrection_job"
TASK_SWEEP = "revive.sweep_orphan_sandboxes"


def redis_url(config: Config | None = None) -> str:
    """Redis URL for broker and result backend, dev default `redis://localhost:6379/0`."""

    from_env = os.getenv("REDIS_URL", "").strip()
    if from_env:
        return from_env
    if config is not None and config.redis_url:
        return config.redis_url
    return "redis://localhost:6379/0"


def create_celery(url: str | None = None) -> Celery:
    broker = url or redis_url()
    app = Celery(
        "revive",
        broker=broker,
        backend=broker,
        include=["revive_api.tasks.pipeline", "revive_api.tasks.sweeper"],
    )
    app.conf.update(
        task_default_queue=DEFAULT_QUEUE,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_acks_on_failure_or_timeout=False,
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=10,
        broker_connection_retry_on_startup=True,
        result_expires=3600,
        timezone="UTC",
        task_track_started=True,
        beat_schedule={
            "sweep-orphan-sandboxes": {
                "task": TASK_SWEEP,
                "schedule": SWEEP_INTERVAL_SECONDS,
            }
        },
    )
    app.conf.task_routes = {TASK_PIPELINE: {"queue": DEFAULT_QUEUE}, TASK_SWEEP: {"queue": DEFAULT_QUEUE}}
    return app


celery_app = create_celery()

__all__ = [
    "DEFAULT_QUEUE",
    "SWEEP_INTERVAL_SECONDS",
    "TASK_PIPELINE",
    "TASK_SWEEP",
    "celery_app",
    "create_celery",
    "redis_url",
]
