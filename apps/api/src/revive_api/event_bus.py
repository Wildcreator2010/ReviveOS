"""One serialization seam and one event transport for job events (T-BE-06).

Red line from `docs/tasks/05`: the writer side and the SSE side must not hand-build
JSON twice.  `serialize_event` is the only encoder, `is_terminal` the only
stream-closing rule, and `sse_frames` the only SSE framing loop.

Redis is a transport, never a hard dependency: when it is missing or flaky the live
channel degrades to process-local fan-out and logs at info level, so
`/jobs/{id}/events/stream` still replays history instead of returning 500.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, cast

import structlog

log = structlog.get_logger(__name__)

CHANNEL_PREFIX = "revive:events:"
TERMINAL_EVENT_TYPES = frozenset({"job.succeeded", "job.failed"})
HEARTBEAT_SECONDS = 15.0


def channel_for(job_id: str) -> str:
    return f"{CHANNEL_PREFIX}{job_id}"


def serialize_event(event: Mapping[str, Any]) -> str:
    """Canonical JSON for a job-event; byte-identical on both sides of the wire."""

    return json.dumps(dict(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def deserialize_event(raw: str | bytes) -> dict[str, Any]:
    payload = raw.decode() if isinstance(raw, bytes) else raw
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("job-event payload must be an object")
    return decoded


def event_envelope(record: Any) -> dict[str, Any]:
    """Accept an envelope mapping or anything that renders one through ``as_dict``."""

    if isinstance(record, Mapping):
        return dict(record)
    as_dict = getattr(record, "as_dict", None)
    if callable(as_dict):
        return dict(as_dict())
    raise TypeError(f"cannot derive a job-event envelope from {type(record)!r}")


def is_terminal(event: Mapping[str, Any]) -> bool:
    return str(event.get("type")) in TERMINAL_EVENT_TYPES


class EventSink(Protocol):
    """Persistence seam: store the event and replay it later."""

    async def add_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def history(self, job_id: str, after_id: str | None) -> list[dict[str, Any]]: ...


class EventPublisher(Protocol):
    async def publish(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class EnvelopeStream(Protocol):
    """Anything that can await the next envelope; `asyncio.Queue` already qualifies."""

    async def get(self) -> dict[str, Any]: ...


class EventStreamSource(Protocol):
    def subscribe(self, job_id: str) -> EnvelopeStream: ...

    def unsubscribe(self, job_id: str, handle: EnvelopeStream) -> None: ...

    async def history(self, job_id: str, after_id: str | None) -> list[dict[str, Any]]: ...


class InProcessRegistry:
    """Local fan-out hub, also the fallback transport while Redis is unavailable."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues.setdefault(job_id, []).append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._queues.get(job_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._queues.pop(job_id, None)

    def broadcast(self, job_id: str, envelope: Mapping[str, Any]) -> None:
        for queue in list(self._queues.get(job_id, [])):
            queue.put_nowait(dict(envelope))

    def waiters(self) -> int:
        return sum(len(queues) for queues in self._queues.values())


class MemorySink:
    """`MemoryStore` behind the sink protocol (dev API and the inline executor)."""

    def __init__(self, store: Any) -> None:
        self.store = store

    async def add_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return event_envelope(self.store.event_bus.publish(job_id, event_type, payload))

    async def history(self, job_id: str, after_id: str | None) -> list[dict[str, Any]]:
        return [event_envelope(record) for record in self.store.events_for_job(job_id, after_id)]


class StoreEventBus:
    """Single-process bus: the store's own asyncio queue fan-out is the transport."""

    def __init__(self, store: Any) -> None:
        self.store = store

    async def publish(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return event_envelope(self.store.event_bus.publish(job_id, event_type, payload))

    def subscribe(self, job_id: str) -> EnvelopeStream:
        return _RecordQueue(self.store.event_bus.subscribe(job_id))

    def unsubscribe(self, job_id: str, handle: EnvelopeStream) -> None:
        self.store.event_bus.unsubscribe(job_id, getattr(handle, "source", handle))

    async def history(self, job_id: str, after_id: str | None) -> list[dict[str, Any]]:
        return [event_envelope(record) for record in self.store.events_for_job(job_id, after_id)]


class RedisEventBus:
    """Write-through bus: persist first, then publish on `revive:events:{job_id}`.

    Safe across processes -- the API can stream events published by a worker in
    another process.  Every Redis failure path degrades to `registry` fan-out.
    """

    def __init__(
        self,
        sink: EventSink,
        client: Any,
        registry: InProcessRegistry | None = None,
        *,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> None:
        self.sink = sink
        self.client = client
        self.registry = registry if registry is not None else InProcessRegistry()
        self.heartbeat_seconds = heartbeat_seconds
        self._pumps: dict[int, asyncio.Task[None]] = {}

    async def publish(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        envelope = await self.sink.add_event(job_id, event_type, payload)
        try:
            await self.client.publish(channel_for(job_id), serialize_event(envelope))
        except Exception as exc:  # noqa: BLE001 - a job must never fail because a subscriber lagged
            log.info("event_bus.redis_publish_failed", job_id=job_id, error=f"{type(exc).__name__}: {exc}")
        self.registry.broadcast(job_id, envelope)
        return envelope

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue = self.registry.subscribe(job_id)
        self._pumps[id(queue)] = asyncio.create_task(self._pump(job_id, queue))
        return queue

    def unsubscribe(self, job_id: str, handle: EnvelopeStream) -> None:
        queue = cast("asyncio.Queue[dict[str, Any]]", handle)
        task = self._pumps.pop(id(queue), None)
        if task is not None:
            task.cancel()
        self.registry.unsubscribe(job_id, queue)

    async def history(self, job_id: str, after_id: str | None) -> list[dict[str, Any]]:
        return await self.sink.history(job_id, after_id)

    async def live(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        handle = self.subscribe(job_id)
        try:
            while True:
                envelope = await handle.get()
                yield envelope
                if is_terminal(envelope):
                    return
        finally:
            self.unsubscribe(job_id, handle)

    async def _pump(self, job_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        channel = channel_for(job_id)
        pubsub = None
        try:
            pubsub = self.client.pubsub()
            await pubsub.subscribe(channel)
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=self.heartbeat_seconds)
                if not message or not message.get("data"):
                    continue
                try:
                    queue.put_nowait(deserialize_event(message["data"]))
                except (ValueError, TypeError) as exc:
                    log.info("event_bus.redis_message_undecodable", error=f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - degrade to local fan-out instead of failing the stream
            log.info("event_bus.redis_subscribe_failed", job_id=job_id, error=f"{type(exc).__name__}: {exc}")
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:  # noqa: BLE001 - closing a degraded subscription is best effort
                    pass


class _RecordQueue:
    """Adapter that makes the store's record queue look like an envelope queue."""

    def __init__(self, source: asyncio.Queue[Any]) -> None:
        self.source = source

    async def get(self) -> dict[str, Any]:
        return event_envelope(await self.source.get())


def sse_frame(envelope: Mapping[str, Any]) -> dict[str, str]:
    """One SSE frame; `data` is the contracted job-event and nothing else builds it."""

    return {
        "id": str(envelope.get("id", "")),
        "event": str(envelope.get("type", "")),
        "data": serialize_event(envelope),
    }


async def sse_frames(
    bus: EventStreamSource,
    job_id: str,
    after_id: str | None = None,
    *,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[dict[str, str]]:
    """Subscribe before the history snapshot so a publish between the two is never lost."""

    handle = bus.subscribe(job_id)
    seen: set[str] = set()
    try:
        for envelope in await bus.history(job_id, after_id):
            frame = sse_frame(envelope)
            if frame["id"] in seen:
                continue
            seen.add(frame["id"])
            yield frame
            if is_terminal(envelope):
                return
        while True:
            try:
                envelope = await asyncio.wait_for(handle.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                yield {"comment": "heartbeat"}
                continue
            frame = sse_frame(envelope)
            if frame["id"] in seen:
                continue
            seen.add(frame["id"])
            yield frame
            if is_terminal(envelope):
                return
    finally:
        bus.unsubscribe(job_id, handle)


class AgentEventPort:
    """Adapter from the supervisor's `EventPort.emit(event)` to an `EventPublisher`."""

    def __init__(self, publisher: EventPublisher) -> None:
        self.publisher = publisher

    async def emit(self, event: dict[str, Any]) -> None:
        await self.publisher.publish(str(event["job_id"]), str(event["type"]), dict(event["payload"]))


__all__ = [
    "AgentEventPort",
    "CHANNEL_PREFIX",
    "EnvelopeStream",
    "EventPublisher",
    "EventSink",
    "EventStreamSource",
    "HEARTBEAT_SECONDS",
    "InProcessRegistry",
    "MemorySink",
    "RedisEventBus",
    "StoreEventBus",
    "TERMINAL_EVENT_TYPES",
    "channel_for",
    "deserialize_event",
    "event_envelope",
    "is_terminal",
    "serialize_event",
    "sse_frame",
    "sse_frames",
]
