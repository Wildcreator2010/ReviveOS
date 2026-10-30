"""Shared HTTP transport for LLM adapters: timeout, retry and backoff.

Adapters speak plain JSON over httpx, so one code path serves OpenAI,
Anthropic and any OpenAI-compatible 'custom' endpoint.  Transport retries are
deliberately separate from the single structured-output retry performed by the
adapters.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from ..observability.tracing import scrub
from .base import LLMError

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF = 0.5
MAX_RESPONSE_BYTES = int(os.getenv("REVIVE_LLM__MAX_RESPONSE_BYTES", str(4 * 1024 * 1024)))
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

SleepFn = Callable[[float], Awaitable[None]]

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def validate_base_url(url: str) -> None:
    """Reject cleartext non-loopback endpoints and obvious private-network targets."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LLMError("LLM base_url must be an http(s) URL with a hostname")
    if parsed.username or parsed.password:
        raise LLMError("LLM base_url must not embed credentials")
    host = parsed.hostname.lower()
    if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise LLMError("LLM base_url must use https outside loopback")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_loopback and (address.is_private or address.is_link_local or address.is_reserved):
        raise LLMError("LLM base_url must not point at a private or link-local address")


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


async def _read_limited(response: httpx.Response, limit: int | None = None) -> bytes:
    if limit is None:
        limit = MAX_RESPONSE_BYTES
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise LLMError(f"LLM response exceeds the {limit} byte size limit")
    return bytes(body)


def _decode_body(raw: bytes) -> str:
    return scrub(raw.decode("utf-8", "replace"))


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
            async with client.stream("POST", url, headers=headers, json=payload, timeout=timeout) as response:
                if response.status_code < 400:
                    raw = await _read_limited(response)
                    try:
                        body = json.loads(raw)
                    except ValueError as exc:
                        raise LLMError(f"{error_prefix}: response was not valid JSON") from exc
                    if not isinstance(body, dict):
                        raise LLMError(f"{error_prefix}: response JSON was not an object")
                    return body
                if response.status_code not in RETRYABLE_STATUS:
                    detail = _decode_body(await _read_limited(response, 300))
                    raise LLMError(f"{error_prefix} failed with HTTP {response.status_code}: {detail}")
                last_error = f"HTTP {response.status_code}"
        except httpx.TimeoutException:
            last_error = f"timeout after {timeout:g}s"
        except httpx.TransportError as exc:
            last_error = f"transport error: {type(exc).__name__}"
        attempt += 1
        if attempt > max_retries:
            raise LLMError(f"{error_prefix} failed after {attempt} attempt(s): {last_error}")
        await sleeper(base_backoff * (2 ** (attempt - 1)))
