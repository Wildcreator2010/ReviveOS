"""Cross-cutting HTTP middleware."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming_id = request.headers.get("X-Request-Id", "")
        request_id = (
            incoming_id
            if len(incoming_id) <= 128 and incoming_id.isascii() and incoming_id.isprintable()
            else f"req_{uuid.uuid4().hex}"
        )
        request.state.request_id = request_id
        # ASGI scope survives exception handling outside BaseHTTPMiddleware's task.
        request.scope["revive_request_id"] = request_id
        try:
            response = await call_next(request)
        except Exception:
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
