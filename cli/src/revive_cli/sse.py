"""Server-Sent Events parsing for the event stream (T-CLI-01)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Iterator
from dataclasses import dataclass
from typing import Any


@dataclass
class ServerEvent:
    event: str
    data: str
    id: str = ""

    def json(self) -> Any:
        try:
            return json.loads(self.data)
        except ValueError:
            return None


def parse_sse_lines(lines: Iterable[str]) -> Iterator[ServerEvent]:
    """Parse an SSE byte/line stream into events (comments and blanks skipped)."""

    event = ""
    data: list[str] = []
    identifier = ""
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                yield ServerEvent(event=event or "message", data="\n".join(data), id=identifier)
            event, data, identifier = "", [], ""
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
        elif field == "id":
            identifier = value
    if data:
        yield ServerEvent(event=event or "message", data="\n".join(data), id=identifier)


async def iter_sse(response: Any) -> AsyncIterator[ServerEvent]:
    """Yield events from an httpx streaming response."""

    buffer: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            for event in parse_sse_lines([*buffer, ""]):
                yield event
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        for event in parse_sse_lines([*buffer, ""]):
            yield event


__all__ = ["ServerEvent", "parse_sse_lines", "iter_sse"]
