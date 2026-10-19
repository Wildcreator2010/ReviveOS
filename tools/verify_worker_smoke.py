#!/usr/bin/env python3
"""Celery smoke check: submit a job, let a worker consume it, prove PG + Redis.

Run it in two terminals with the dev compose stack up (PostgreSQL + Redis):

  1. migrate once:
     DATABASE_URL=postgresql+asyncpg://revive:revive@localhost:5432/revive \
       .venv\\Scripts\\python.exe -m alembic -c apps\\api\\alembic.ini upgrade head

  2. start the worker (Windows needs --pool=solo; Celery has no prefork there):
     DATABASE_URL=... REDIS_URL=redis://localhost:6379/0 \
       .venv\\Scripts\\python.exe -m celery -A revive_api.celery_app worker -l info --pool=solo -Q revive

  3. submit and verify:
     DATABASE_URL=... REDIS_URL=... .venv\\Scripts\\python.exe tools\\verify_worker_smoke.py

Exit code 0 only when the job reached a terminal state, its `job_events` rows all
validate against schemas/job-event.schema.json, and the Redis channel carried the
terminal envelope byte-identically to the persisted row.  With no usable Docker
daemon the terminal state is `failed` (reason `worker_error`) -- that still proves
the broker, the persistence seam and the event transport; with Docker available the
same run ends `succeeded`.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for source in (
    REPO_ROOT / "apps" / "api" / "src",
    REPO_ROOT / "packages" / "core" / "src",
    REPO_ROOT / "agents" / "src",
):
    sys.path.insert(0, str(source))

import redis.asyncio as aioredis  # noqa: E402
from revive_api.celery_app import redis_url  # noqa: E402
from revive_api.db.repository import ControlPlaneRepository  # noqa: E402
from revive_api.event_bus import channel_for, deserialize_event, is_terminal, serialize_event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

TERMINAL = {"succeeded", "failed", "cancelled"}
POLL_SECONDS = 180.0


def write_fixture_project(root: Path) -> Path:
    source = root / "smoke-src"
    (source / "tests").mkdir(parents=True, exist_ok=True)
    (source / "hello.py").write_text("def run() -> int:\n    return 0\n", encoding="utf-8")
    (source / "requirements.txt").write_text("", encoding="utf-8")
    (source / "tests" / "test_hello.py").write_text("def test_noop():\n    assert True\n", encoding="utf-8")
    return source


async def seed_job(url: str, source: Path) -> str:
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            repository = ControlPlaneRepository(session)
            stamp = int(time.time() * 1000)
            user = await repository.add_user(f"smoke{stamp}@e.example", "hash")
            project = await repository.add_project(
                user.id, f"https://github.com/acme/smoke{stamp}", f"acme/smoke{stamp}"
            )
            job = await repository.add_job(project.id, user.id)
            await repository.set_job_metadata(
                job.id,
                source_path=str(source),
                pipeline={"build_argv": [sys.executable, "-c", "print('built')"]},
            )
            await repository.commit()
            return job.id
    finally:
        await engine.dispose()


async def collect_until_terminal(channel: str, deadline: float) -> list[dict[str, Any]]:
    client = aioredis.from_url(redis_url())
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    received: list[dict[str, Any]] = []
    try:
        while time.monotonic() < deadline:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None or not message.get("data"):
                continue
            envelope = deserialize_event(message["data"])
            received.append(envelope)
            if is_terminal(envelope):
                return received
    finally:
        await pubsub.aclose()
        await client.aclose()
    return received


async def read_events(url: str, job_id: str) -> tuple[list[dict[str, Any]], str]:
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            repository = ControlPlaneRepository(session)
            rows = await repository.events_for_job(job_id)
            job = await repository.get_job(job_id)
            return [row.as_dict() for row in rows], (job.status if job else "missing")
    finally:
        await engine.dispose()


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=POLL_SECONDS)
    args = parser.parse_args(argv)

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("FAIL: DATABASE_URL is not set", file=sys.stderr)
        return 2

    work = Path(REPO_ROOT) / ".revive-tmp" / f"worker-smoke-{int(time.time())}"
    work.mkdir(parents=True, exist_ok=True)
    source = write_fixture_project(work)

    job_id = await seed_job(database_url, source)
    channel = channel_for(job_id)
    deadline = time.monotonic() + args.timeout
    collector = asyncio.create_task(collect_until_terminal(channel, deadline))

    from revive_api.tasks.pipeline import run_resurrection_job

    result = run_resurrection_job.delay(job_id)
    print(f"submitted job {job_id} as celery task {result.id} on channel {channel}")

    status = "queued"
    events: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        events, status = await read_events(database_url, job_id)
        if status in TERMINAL:
            break
        await asyncio.sleep(1.0)

    published = await collector
    problems: list[str] = []
    if status not in TERMINAL:
        problems.append(f"job {job_id} never reached a terminal state (last={status}, events={len(events)})")
    if not events:
        problems.append("no job_events rows were persisted")
    if not published:
        problems.append("nothing arrived on the Redis channel")
    if events and published and published[-1] != events[-1]:
        problems.append("the terminal envelope on Redis differs from the persisted row")
    if published and not is_terminal(published[-1]):
        problems.append("the last Redis message was not a terminal event")

    from revive_core import schemas

    for row in events:
        try:
            schemas.validate(row, "job-event")
        except schemas.SchemaError as exc:
            problems.append(f"{row.get('type')}: {exc}")
    for envelope in published:
        encoded = serialize_event(envelope)
        if serialize_event(deserialize_event(encoded)) != encoded:
            problems.append("serialize_event is not stable across a round trip")

    print(f"status={status} persisted_events={len(events)} redis_events={len(published)}")
    print("event types:", ", ".join(str(row.get("type")) for row in events) or "-")
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
