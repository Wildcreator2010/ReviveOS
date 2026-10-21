"""Application dependencies and readiness probes.

A probe answers one question: can this process serve traffic that depends on the
component? The API soft-fails Redis (the SSE transport degrades to in-process fan-out),
but it cannot serve capsules without object storage, so that probe is part of readiness.
"""

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


def _object_storage_probe(endpoint: str, bucket: str) -> Probe:
    """HEAD the bucket: any HTTP answer means the store is reachable and answering.

    A 403 on a private bucket is a *successful* probe (the service is up, the caller is
    anonymous); only transport failures and 5xx mean "not ready". Proxies are bypassed
    for the same reason the capsule client bypasses them.
    """

    if not endpoint.strip():
        return lambda: True
    url = f"{endpoint.rstrip('/')}/{bucket.strip('/')}"

    def probe() -> bool:
        import httpx

        try:
            response = httpx.head(url, timeout=2.0, trust_env=False)
        except httpx.HTTPError:
            return False
        # 403 = bucket exists but the anonymous probe lacks permission; 404 means
        # the bucket (or path-style endpoint) is missing, so writes will fail.
        return response.status_code < 500 and response.status_code != 404

    return probe


def readiness_probes(config: Config) -> dict[str, Probe]:
    return {
        "postgres": _tcp_probe(config.database_url, 5432),
        "redis": _tcp_probe(config.redis_url, 6379),
        "object_storage": _object_storage_probe(config.s3_endpoint, config.s3_bucket),
    }


__all__ = ["Probe", "readiness_probes", "run_probe"]
