"""Request-scoped async SQLAlchemy unit of work for control-plane handlers."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .repository import ControlPlaneRepository

_current: ContextVar[ControlPlaneRepository | None] = ContextVar("revive_control_plane_uow", default=None)


class UnitOfWorkError(RuntimeError):
    pass


class RequestControlPlane:
    """Stable app-level facade dispatching to the current request repository."""

    durable = True

    def __init__(self, fallback: Any = None) -> None:
        self.fallback = fallback

    def bind(self, repository: ControlPlaneRepository) -> Token[ControlPlaneRepository | None]:
        return _current.set(repository)

    def reset(self, token: Token[ControlPlaneRepository | None]) -> None:
        _current.reset(token)

    async def commit_current(self) -> None:
        target = self._target()
        commit = getattr(target, "commit", None)
        if not callable(commit):
            raise UnitOfWorkError("active control-plane does not support commit")
        await commit()

    def _target(self) -> Any:
        target = _current.get()
        if target is not None:
            return target
        if self.fallback is not None:
            return self.fallback
        raise UnitOfWorkError("control-plane operation requires an active request unit of work")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)


class SQLAlchemyUnitOfWorkMiddleware:
    """Opens one session per HTTP request and commits only successful responses."""

    def __init__(
        self,
        app: Any,
        sessions: async_sessionmaker[AsyncSession] | Any,
        control_plane: RequestControlPlane,
    ) -> None:
        self.app = app
        self.sessions = sessions
        self.control_plane = control_plane

    def _session_context(self) -> Any:
        return self.sessions() if callable(self.sessions) else self.sessions

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") in {"/healthz", "/readyz"}:
            await self.app(scope, receive, send)
            return
        session_context = self._session_context()
        if session_context is None:
            await self.app(scope, receive, send)
            return
        async with session_context as session:
            repository = ControlPlaneRepository(session)
            token = self.control_plane.bind(repository)
            finalized = False

            async def capture_status(message: dict[str, Any]) -> None:
                nonlocal finalized
                if message["type"] == "http.response.start" and not finalized:
                    if int(message["status"]) < 400:
                        await session.commit()
                    else:
                        await session.rollback()
                    self.control_plane.reset(token)
                    await session.close()
                    finalized = True
                await send(message)

            try:
                await self.app(scope, receive, capture_status)
                if not finalized:
                    await session.commit()
            except BaseException:
                if not finalized:
                    await session.rollback()
                raise
            finally:
                if not finalized:
                    self.control_plane.reset(token)


__all__ = ["RequestControlPlane", "SQLAlchemyUnitOfWorkMiddleware", "UnitOfWorkError"]
