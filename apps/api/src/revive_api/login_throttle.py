"""Login throttling port with memory (dev) and Redis (production) implementations."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol


class LoginThrottle(Protocol):
    durable: bool

    async def check(self, key: str) -> int | None: ...
    async def failed(self, key: str, *, limit: int, lockout: int) -> int | None: ...
    async def succeeded(self, key: str) -> None: ...


class MemoryLoginThrottle:
    durable = False

    def __init__(self) -> None:
        self._failures: dict[str, tuple[int, datetime]] = {}

    async def check(self, key: str) -> int | None:
        failures, locked_until = self._failures.get(key, (0, datetime.min.replace(tzinfo=UTC)))
        if locked_until <= datetime.now(UTC):
            return None
        return max(1, int((locked_until - datetime.now(UTC)).total_seconds()))

    async def failed(self, key: str, *, limit: int, lockout: int) -> int | None:
        failures, locked_until = self._failures.get(key, (0, datetime.min.replace(tzinfo=UTC)))
        failures += 1
        if failures >= limit:
            locked_until = datetime.now(UTC) + timedelta(minutes=lockout)
        self._failures[key] = (failures, locked_until)
        if locked_until > datetime.now(UTC):
            return max(1, int((locked_until - datetime.now(UTC)).total_seconds()))
        return None

    async def succeeded(self, key: str) -> None:
        self._failures.pop(key, None)


class RedisLoginThrottle:
    """Shared login throttle so every API replica sees the same lockout state."""

    durable = True
    PREFIX = "revive:login:"

    def __init__(self, client: Any) -> None:
        self.client = client

    @staticmethod
    def _digest(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def _failure_key(self, key: str) -> str:
        return f"{self.PREFIX}fail:{self._digest(key)}"

    def _lock_key(self, key: str) -> str:
        return f"{self.PREFIX}lock:{self._digest(key)}"

    async def check(self, key: str) -> int | None:
        ttl = await self.client.ttl(self._lock_key(key))
        return int(ttl) if ttl and int(ttl) > 0 else None

    async def failed(self, key: str, *, limit: int, lockout: int) -> int | None:
        failures = int(await self.client.incr(self._failure_key(key)))
        await self.client.expire(self._failure_key(key), lockout * 60)
        if failures < limit:
            return None
        await self.client.set(self._lock_key(key), "1", ex=lockout * 60)
        return lockout * 60

    async def succeeded(self, key: str) -> None:
        await self.client.delete(self._failure_key(key), self._lock_key(key))


__all__ = ["LoginThrottle", "MemoryLoginThrottle", "RedisLoginThrottle"]
