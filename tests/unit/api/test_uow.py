from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from revive_api.db.uow import RequestControlPlane, SQLAlchemyUnitOfWorkMiddleware


class Session:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


class Repository:
    pass


class App:
    async def __call__(self, scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": scope["status"]})
        await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "committed", "rolled_back"), [(200, True, False), (422, False, True)])
async def test_uow_commits_success_and_rolls_back_error_responses(status, committed, rolled_back) -> None:
    session = Session()

    @asynccontextmanager
    async def factory():
        yield session

    facade = RequestControlPlane()
    middleware = SQLAlchemyUnitOfWorkMiddleware(App(), factory, facade)
    sent = []

    async def send(message):
        sent.append(message)

    await middleware({"type": "http", "path": "/api/v1/jobs", "status": status}, None, send)
    assert session.committed is committed
    assert session.rolled_back is rolled_back
    assert session.closed


@pytest.mark.asyncio
async def test_uow_rolls_back_application_exceptions() -> None:
    session = Session()

    @asynccontextmanager
    async def factory():
        yield session

    class Broken:
        async def __call__(self, scope, receive, send):
            raise RuntimeError("route failed")

    middleware = SQLAlchemyUnitOfWorkMiddleware(Broken(), factory, RequestControlPlane())
    with pytest.raises(RuntimeError, match="route failed"):
        await middleware({"type": "http", "path": "/api/v1/jobs"}, None, lambda message: None)
    assert session.rolled_back
