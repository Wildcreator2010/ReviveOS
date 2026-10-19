"""Short-lived PostgreSQL event sink used by RedisEventBus."""

from __future__ import annotations

from typing import Any

from ..db.repository import ControlPlaneRepository
from ..event_bus import event_envelope


def sequence_of(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(cursor.rsplit("_", 1)[-1])
    except ValueError:
        return 0


class SessionEventSink:
    """Open an independent DB session per event write/history query."""

    def __init__(self, sessions: Any) -> None:
        self.sessions = sessions

    async def add_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.sessions() as session:
            repository = ControlPlaneRepository(session)
            record = await repository.add_event(job_id, event_type, payload)
            await session.commit()
            return event_envelope(record)

    async def history(self, job_id: str, after_id: str | None) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            records = await ControlPlaneRepository(session).events_for_job(job_id, sequence_of(after_id))
            return [event_envelope(record) for record in records]


__all__ = ["SessionEventSink", "sequence_of"]
