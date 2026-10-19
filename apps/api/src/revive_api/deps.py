"""Application dependencies and readiness probes."""

from __future__ import annotations

import inspect
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from .config import Config

Probe = Callable[[], bool | Awaitable[bool]]


async def run_probe(probe: Probe) -> bool:
    result = probe()
    return bool(await result) if inspect.isawaitable(result) else bool(result)


def _tcp_probe(url: str, default_port: int) -> Probe:
    parsed = urlparse(url)
    if not url.strip():
        return lambda: True
    host = parsed.hostname or "localhost"
    port = parsed.port or default_port

    def probe() -> bool:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            return False

    return probe


def readiness_probes(config: Config) -> dict[str, Probe]:
    return {
        "postgres": _tcp_probe(config.database_url, 5432),
        "redis": _tcp_probe(config.redis_url, 6379),
    }
