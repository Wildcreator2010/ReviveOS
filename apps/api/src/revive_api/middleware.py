"""Cross-cutting HTTP middleware."""

from __future__ import annotations

import hmac
import re
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger(__name__)

_CAPSULE_PATH = re.compile(r"^/api/v1/jobs/[^/]+/capsule$")


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject oversized bodies before FastAPI parses them.

    Unauthenticated capsule uploads are rejected from headers alone, so an
    anonymous caller cannot force the API to buffer a large JSON document.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int,
        capsule_max_bytes: int,
        worker_token: str,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.capsule_max_bytes = capsule_max_bytes
        self.worker_token = worker_token.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        is_capsule = scope.get("method") == "POST" and bool(_CAPSULE_PATH.match(scope.get("path", "")))
        if is_capsule:
            supplied = headers.get("x-worker-token", "").encode("utf-8")
            if not supplied or not hmac.compare_digest(supplied, self.worker_token):
                await _json_error(scope, receive, send, 401, "unauthorized", "worker authentication required")
                return

        limit = self.capsule_max_bytes if is_capsule else self.max_bytes
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                await _json_error(scope, receive, send, 400, "invalid_content_length", "Content-Length is invalid")
                return
            if declared > limit:
                await _json_error(
                    scope, receive, send, 413, "payload_too_large", "request body exceeds the configured limit"
                )
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            if response_started:
                raise
            await _json_error(
                scope, receive, send, 413, "payload_too_large", "request body exceeds the configured limit"
            )


async def _json_error(scope: Scope, receive: Receive, send: Send, status: int, code: str, message: str) -> None:
    response = JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})
    await response(scope, receive, send)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming_id = request.headers.get("X-Request-Id", "")
        request_id = (
            incoming_id
            if len(incoming_id) <= 128 and incoming_id.isascii() and incoming_id.isprintable()
            else f"req_{uuid.uuid4().hex}"
        )
        request.state.request_id = request_id
        # ASGI scope survives exception handling outside BaseHTTPMiddleware's task.
        request.scope["revive_request_id"] = request_id
        response: Response
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "http.unhandled_exception",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "internal",
                        "message": "Internal server error",
                        "request_id": request_id,
                    }
                },
            )
        response.headers["X-Request-Id"] = request_id
        return response
