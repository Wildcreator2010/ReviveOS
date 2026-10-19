"""T-BE-06: one encoder, one stream loop, and a Redis outage that must not 500."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from revive_api.config import Config
from revive_api.event_bus import (
    AgentEventPort,
    InProcessRegistry,
    RedisEventBus,
    StoreEventBus,
    channel_for,
    deserialize_event,
    serialize_event,
    sse_frames,
)
from revive_api.main import create_app
from revive_api.store import MemoryStore
from revive_core import schemas

pytestmark = pytest.mark.asyncio


def envelope(sequence: int, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": f"evt_{sequence:012d}",
        "job_id": "job_1",
        "project_id": "project_1",
        "ts": "2026-01-01T00:00:00+00:00",
        "type": event_type,
        "payload": payload if payload is not None else {"status": "queued"},
    }


class DictSink:
    """Sink that keeps envelopes in a list, so no store is involved."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._sequence = 0

    async def add_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._sequence += 1
        row = envelope(self._sequence, event_type, payload)
        self.rows.append(row)
        return row

    async def history(self, job_id: str, after_id: str | None) -> list[dict[str, Any]]:
        return list(self.rows)


class BlockedPubsub:
    def __init__(self) -> None:
        self.unsubscribed = False

    async def subscribe(self, channel: str) -> None:
        return None

    async def get_message(self, **kwargs: Any) -> None:
        await asyncio.sleep(3600)
        return None

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed = True

    async def aclose(self) -> None:
        return None


class RecordingRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.published: list[tuple[str, str]] = []
        self.fail = fail

    async def publish(self, channel: str, message: str) -> int:
        if self.fail:
            raise ConnectionError("redis is down")
        self.published.append((channel, message))
        return 1

    def pubsub(self) -> Any:
        if self.fail:
            raise ConnectionError("redis is down")
        return BlockedPubsub()


def store_with_events(*types: str) -> tuple[MemoryStore, str]:
    store = MemoryStore()
    project = store.add_project("user_1", "https://github.com/acme/bus")
    job = store.add_job(project)
    payloads: dict[str, dict[str, Any]] = {
        "job.queued": {"status": "queued"},
        "build.attempt": {"attempt": 1, "ok": False},
        "job.succeeded": {"status": "succeeded"},
        "job.failed": {"status": "failed", "reason": "boom"},
    }
    for event_type in types:
        store.event_bus.publish(job.id, event_type, payloads.get(event_type, {}))
    return store, job.id


async def drain(bus: Any, job_id: str, after_id: str | None = None, *, limit: int = 20) -> list[dict[str, str]]:
    frames: list[dict[str, str]] = []
    async for frame in sse_frames(bus, job_id, after_id, heartbeat_seconds=0.05):
        frames.append(frame)
        if len(frames) >= limit:
            break
    return frames


async def test_serialize_event_is_byte_stable_regardless_of_insertion_order() -> None:
    first = {"b": 1, "a": {"y": 2, "x": [1, 2]}}
    second = {"a": {"x": [1, 2], "y": 2}, "b": 1}
    assert serialize_event(first) == serialize_event(second)
    assert serialize_event(first) == '{"a":{"x":[1,2],"y":2},"b":1}'
    assert deserialize_event(serialize_event(first)) == first


async def test_sse_and_publisher_emit_identical_bytes_for_one_event() -> None:
    bus = RedisEventBus(DictSink(), RecordingRedis(), InProcessRegistry())
    published = await bus.publish("job_1", "build.attempt", {"attempt": 1, "ok": False})
    frames = await drain(bus, "job_1", limit=1)

    assert bus.client.published == [(channel_for("job_1"), serialize_event(published))]
    assert frames[0]["data"] == serialize_event(published)
    assert json.loads(frames[0]["data"]) == published


async def test_store_bus_replays_history_and_stops_on_terminal() -> None:
    store, job_id = store_with_events("job.queued", "build.attempt", "job.succeeded", "job.failed")
    frames = await drain(StoreEventBus(store), job_id)

    assert [frame["event"] for frame in frames] == ["job.queued", "build.attempt", "job.succeeded"]
    for frame in frames:
        schemas.validate(deserialize_event(frame["data"]), "job-event")


async def test_last_event_id_cursor_replays_only_the_tail() -> None:
    store, job_id = store_with_events("job.queued", "build.attempt", "job.succeeded")
    frames = await drain(StoreEventBus(store), job_id, "evt_000000000001")
    assert [frame["id"] for frame in frames] == ["evt_000000000002", "evt_000000000003"]


async def test_redis_outage_degrades_without_breaking_the_stream() -> None:
    bus = RedisEventBus(DictSink(), RecordingRedis(fail=True), InProcessRegistry())
    published = await bus.publish("job_1", "job.queued", {"status": "queued"})

    assert published["type"] == "job.queued"
    assert bus.client.published == []
    frames = await drain(bus, "job_1", limit=1)
    assert frames[0]["data"] == serialize_event(published)


async def test_live_events_reach_the_subscriber_and_the_stream_closes() -> None:
    bus = RedisEventBus(DictSink(), RecordingRedis(), InProcessRegistry())
    received: list[dict[str, Any]] = []

    async def consume() -> None:
        async for event in bus.live("job_1"):
            received.append(event)

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.sleep(0.01)  # let the subscriber register before the first publish
        await bus.publish("job_1", "job.succeeded", {"status": "succeeded"})
        await asyncio.wait_for(consumer, timeout=1)
    finally:
        consumer.cancel()

    assert [event["type"] for event in received] == ["job.succeeded"]


async def test_agent_event_port_forwards_the_graph_envelope() -> None:
    sink = DictSink()
    bus = RedisEventBus(sink, RecordingRedis(), InProcessRegistry())
    await AgentEventPort(bus).emit(envelope(1, "score.computed", {"total": 61.5}))

    assert sink.rows[0]["payload"] == {"total": 61.5}
    assert bus.client.published[0] == (channel_for("job_1"), serialize_event(sink.rows[0]))


async def test_sse_endpoint_streams_frames_that_satisfy_the_contract() -> None:
    client = TestClient(create_app(Config(jwt_secret="event-bus-secret-at-least-32-characters"), probes={}))
    registered = client.post("/auth/register", json={"email": "sse@e.example", "password": "correct-horse-123"})
    auth = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    store = client.app.state.store
    owner = store.users_by_email["sse@e.example"]

    project = store.add_project(owner, "https://github.com/acme/bus")
    job = store.add_job(project)
    for event_type, payload in (
        ("job.queued", {"status": "queued"}),
        ("build.attempt", {"attempt": 1, "ok": False}),
        ("job.succeeded", {"status": "succeeded"}),
    ):
        store.event_bus.publish(job.id, event_type, payload)

    with client.stream("GET", f"/jobs/{job.id}/events/stream", headers=auth) as response:
        assert response.status_code == 200
        lines = list(response.iter_lines())

    data_lines = [line.removeprefix("data: ") for line in lines if line.startswith("data:")]
    assert len(data_lines) == 3
    assert any(line == "event: job.succeeded" for line in lines)
    for line in data_lines:
        schemas.validate(json.loads(line), "job-event")
    assert data_lines[0] == serialize_event(store.events_for_job(job.id)[0].as_dict())
