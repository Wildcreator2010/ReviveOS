from __future__ import annotations

import pytest
from revive_api.config import Config
from revive_api.main import create_app


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.mark.asyncio
async def test_app_lifespan_creates_and_disposes_configured_database_engine() -> None:
    engine = FakeEngine()
    sessions = object()
    calls: list[str] = []

    def factory(url: str):
        calls.append(url)
        return engine, sessions

    app = create_app(
        Config(database_url="postgresql+asyncpg://db/revive", jwt_secret="test-secret-at-least-32-bytes-long"),
        probes={},
        engine_factory=factory,
    )
    async with app.router.lifespan_context(app):
        assert app.state.db_engine is engine
        assert app.state.db_sessions is sessions
        assert not engine.disposed
    assert engine.disposed
    assert calls == ["postgresql+asyncpg://db/revive"]
