from __future__ import annotations

import pytest
from revive_api.login_throttle import MemoryLoginThrottle, RedisLoginThrottle


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = 1
        if ex:
            self.ttls[key] = ex

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)
            self.ttls.pop(key, None)


@pytest.mark.asyncio
async def test_redis_throttle_locks_after_limit_and_clears_on_success() -> None:
    client = FakeRedis()
    throttle = RedisLoginThrottle(client)
    assert throttle.durable is True
    assert await throttle.check("user@example.com") is None

    assert await throttle.failed("user@example.com", limit=2, lockout=5) is None
    assert await throttle.failed("user@example.com", limit=2, lockout=5) == 300
    assert await throttle.check("user@example.com") == 300

    await throttle.succeeded("user@example.com")
    assert await throttle.check("user@example.com") is None


@pytest.mark.asyncio
async def test_memory_throttle_locks_after_limit() -> None:
    throttle = MemoryLoginThrottle()
    assert throttle.durable is False
    assert await throttle.failed("k", limit=1, lockout=5) is not None
    assert await throttle.check("k") is not None
    await throttle.succeeded("k")
    assert await throttle.check("k") is None
