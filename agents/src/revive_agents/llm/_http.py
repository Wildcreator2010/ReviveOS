"""Shared HTTP transport for LLM adapters: timeout, retry and backoff.

Adapters speak plain JSON over httpx, so one code path serves OpenAI,
Anthropic and any OpenAI-compatible 'custom' endpoint.  Transport retries are
deliberately separate from the single structured-output retry performed by the
adapters.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from ..observability.tracing import scrub
from .base import LLMError

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF = 0.5
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

SleepFn = Callable[[float], Awaitable[None]]


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _safe_body(response: httpx.Response, limit: int = 300) -> str:
    try:
        text = response.text
    except Exception:  # pragma: no cover - defensive
        return "<unreadable body>"
    return scrub(text[:limit])


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
    retries: int | None = None,
    backoff: float | None = None,
    sleep: SleepFn | None = None,
    error_prefix: str = "LLM request",
) -> dict[str, Any]:
    """POST JSON with bounded exponential backoff on timeouts and 5xx/429."""

    max_retries = env_int("REVIVE_LLM__MAX_RETRIES", DEFAULT_MAX_RETRIES) if retries is None else retries
    base_backoff = env_float("REVIVE_LLM__RETRY_BACKOFF", DEFAULT_BACKOFF) if backoff is None else backoff
    sleeper: SleepFn = sleep or asyncio.sleep
    attempt = 0
    last_error = "unknown error"
    while True:
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=timeout)
        except httpx.TimeoutException:
            last_error = f"timeout after {timeout:g}s"
        except httpx.TransportError as exc:
            last_error = f"transport error: {type(exc).__name__}"
        else:
            if response.status_code < 400:
                try:
                    body = response.json()
                except ValueError as exc:
                    raise LLMError(f"{error_prefix}: response was not valid JSON") from exc
                if not isinstance(body, dict):
                    raise LLMError(f"{error_prefix}: response JSON was not an object")
                return body
            if response.status_code not in RETRYABLE_STATUS:
                detail = _safe_body(response)
                raise LLMError(f"{error_prefix} failed with HTTP {response.status_code}: {detail}")
            last_error = f"HTTP {response.status_code}"
        attempt += 1
        if attempt > max_retries:
            raise LLMError(f"{error_prefix} failed after {attempt} attempt(s): {last_error}")
        await sleeper(base_backoff * (2 ** (attempt - 1)))
