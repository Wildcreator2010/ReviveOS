"""T-BE-05: the pipeline task end to end on PostgreSQL + Redis.

Runs the real `execute_job` core against a throwaway schema and real Redis
pub/sub, with `LocalExecutionPort` as the sandbox substitute (a production worker
always uses `DockerExecutionPort`; its refusal path is covered in the unit file).
It proves what the ticket demands: the `job_events` table and the
`revive:events:{job_id}` channel both receive the terminal event, byte-identically;
a finished job is never re-run; a requested cancellation stops the next stage; and
a dead Redis never loses the persisted events.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Self

import pytest
import redis.asyncio as aioredis
from revive_api.db.repository import ControlPlaneRepository
from revive_api.event_bus import InProcessRegistry, RedisEventBus, channel_for, serialize_event
from revive_api.tasks.pipeline import PostgresEventSink, PostgresJobStore, execute_job
from revive_core import schemas
from revive_core.sandbox.port_impl import LocalExecutionPort
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.requires_docker

TEST_DB = "revive_pipeline_test"


def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
def migrated_database(provision_database: Any) -> URL:
    return provision_database(TEST_DB)


def write_fixture_repo(root: Path) -> Path:
    """A small project with real declarations and passing tests, so archaeology and
    the build/test stages both have something genuine to work on."""

    source = root / "src"
    (source / "tests").mkdir(parents=True)
    (source / "hello.py").write_text("def run() -> int:\n    return 0\n", encoding="utf-8")
    (source / "requirements.txt").write_text("flask==1.1.4\nrequests>=2.2\n", encoding="utf-8")
    (source / "setup.py").write_text(
        "from setuptools import setup\n\nsetup(name='hello', python_requires='>=3.6')\n", encoding="utf-8"
    )
    (source / "tests" / "test_hello.py").write_text(
        "import sys\nsys.path.insert(0, '.')\nfrom hello import run\n\n\ndef test_run():\n    assert run() == 0\n",
        encoding="utf-8",
    )
    return source


class Sandbox:
    """One async session, its repository, and the Redis-backed event bus over them."""

    def __init__(
        self,
        engine: AsyncEngine,
        session: AsyncSession,
        repository: ControlPlaneRepository,
        redis: aioredis.Redis,
    ) -> None:
        self.engine = engine
        self.session = session
        self.repository = repository
        self.redis = redis
        self.store = PostgresJobStore(repository)
        self.bus = RedisEventBus(PostgresEventSink(repository), redis)

    @classmethod
    async def create(cls, url: URL) -> Self:
        engine = create_async_engine(url.render_as_string(hide_password=False))
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        session = factory()
        repository = ControlPlaneRepository(session)
        return cls(engine, session, repository, aioredis.from_url(redis_url()))

    async def close(self) -> None:
        await self.session.close()
        await self.redis.aclose()
        await self.engine.dispose()

    async def seed(self, marker: str, source: Path) -> str:
        user = await self.repository.add_user(f"pipeline{marker}@e.example", "hash")
        project = await self.repository.add_project(user.id, f"https://github.com/acme/{marker}", f"acme/{marker}")
        job = await self.repository.add_job(project.id, user.id)
        await self.repository.set_job_metadata(
            job.id,
            source_path=str(source),
            pipeline={"build_argv": [sys.executable, "-c", "print('built')"]},
        )
        await self.repository.commit()
        return job.id

    async def event_types(self, job_id: str) -> list[str]:
        return [event.event_type for event in await self.repository.events_for_job(job_id)]


@pytest.fixture
async def sandbox(migrated_database: URL, tmp_path: Path) -> AsyncIterator[tuple[Sandbox, Path]]:
    handle = await Sandbox.create(migrated_database)
    source = write_fixture_repo(tmp_path)
    try:
        yield handle, source
    finally:
        await handle.close()


def local_port(job_id: str, source: Path) -> LocalExecutionPort:
    return LocalExecutionPort(source=source, job_id=job_id, offline=True)


async def collect_channel(job_id: str) -> list[str]:
    """Subscribe before the job runs and read until the terminal event on the wire."""

    from revive_api.event_bus import deserialize_event, is_terminal

    client = aioredis.from_url(redis_url())
    pubsub = client.pubsub()
    await pubsub.subscribe(channel_for(job_id))
    await asyncio.sleep(0.25)  # the subscription must be live before the first publish
    received: list[str] = []
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
            if message is None or not message.get("data"):
                continue
            data = message["data"]
            text = data.decode() if isinstance(data, bytes) else str(data)
            received.append(text)
            if is_terminal(deserialize_event(text)):
                return received
    finally:
        await pubsub.aclose()
        await client.aclose()


class SilentRedis:
    """Transport that fails every call, to prove persistence does not depend on Redis."""

    async def publish(self, channel: str, message: str) -> int:
        raise ConnectionError("redis is down")

    def pubsub(self) -> aioredis.client.PubSub:
        raise ConnectionError("redis is down")


async def test_pipeline_reaches_succeeded_and_mirrors_events_to_redis(sandbox: tuple[Sandbox, Path]) -> None:
    store, source = sandbox
    job_id = await store.seed("a", source)
    channel = asyncio.create_task(collect_channel(job_id))

    result = await execute_job(job_id, store=store.store, events=store.bus, execution_factory=local_port)
    published = await channel

    assert result.status == "succeeded", result.failure_reason
    types = await store.event_types(job_id)
    assert types[0] == "job.queued"
    assert types[-1] == "job.succeeded"
    assert {"archaeology.started", "env.inferred", "sandbox.created", "build.attempt", "test.attempt"} <= set(types)

    events = await store.repository.events_for_job(job_id)
    for event in events:
        schemas.validate(event.as_dict(), "job-event")
    assert len(published) == len(types)
    assert published[-1] == serialize_event(events[-1].as_dict())

    job = await store.repository.get_job(job_id)
    assert job.status == "succeeded"
    assert job.metadata["genome"]["python"] is not None
    assert job.metadata["events_recorded"] == len(types)


async def test_terminal_job_is_never_re_run(sandbox: tuple[Sandbox, Path]) -> None:
    store, source = sandbox
    job_id = await store.seed("b", source)
    first = await execute_job(job_id, store=store.store, events=store.bus, execution_factory=local_port)
    after_first = await store.repository.events_for_job(job_id)

    second = await execute_job(job_id, store=store.store, events=store.bus, execution_factory=local_port)

    assert first.status in {"succeeded", "failed"}
    assert second.skipped == "already_terminal"
    assert second.status == first.status
    assert len(await store.repository.events_for_job(job_id)) == len(after_first)


async def test_cancel_requested_stops_the_pipeline_and_closes_the_sandbox(sandbox: tuple[Sandbox, Path]) -> None:
    store, source = sandbox
    opened: list[LocalExecutionPort] = []

    def tracking_port(job_id: str, path: Path) -> LocalExecutionPort:
        port = LocalExecutionPort(source=path, job_id=job_id, offline=True)
        opened.append(port)
        return port

    job_id = await store.seed("c", source)
    await store.repository.update_job(job_id, status="running", cancel_requested=True)
    await store.repository.commit()

    result = await execute_job(job_id, store=store.store, events=store.bus, execution_factory=tracking_port)

    assert result.status == "cancelled"
    assert result.failure_reason == "user_cancelled"
    assert (await store.repository.get_job(job_id)).status == "cancelled"
    events = await store.repository.events_for_job(job_id)
    assert events[-1].event_type == "job.failed"
    assert events[-1].payload == {"status": "cancelled", "reason": "user_cancelled"}
    assert opened and opened[0].closed is True


async def test_events_are_persisted_even_when_redis_is_down(sandbox: tuple[Sandbox, Path]) -> None:
    store, source = sandbox
    job_id = await store.seed("d", source)
    degraded = RedisEventBus(PostgresEventSink(store.repository), SilentRedis(), InProcessRegistry())

    result = await execute_job(job_id, store=store.store, events=degraded, execution_factory=local_port)

    assert result.status == "succeeded"
    types = await store.event_types(job_id)
    assert types[-1] == "job.succeeded"
    assert len(types) > 1
