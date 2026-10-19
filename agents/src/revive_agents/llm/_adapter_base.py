"""Shared skeleton for the real HTTP adapters.

Both the OpenAI(-compatible) and Anthropic adapters subclass this.  It owns the
single structured-output retry mandated by T-AG-01: when 'response_format' is
set and the first reply is not parseable JSON, the error is fed back to the
model exactly once; a second failure raises 'LLMOutputError'.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from ._http import DEFAULT_TIMEOUT, SleepFn, post_json
from .base import (
    Completion,
    LLMOutputError,
    Message,
    ReasoningEffort,
    Usage,
    estimate_cost,
    extract_json,
)


@dataclass(frozen=True)
class _Parsed:
    text: str
    usage: Usage
    raw_id: str


def build_retry_messages(messages: Sequence[Message], previous_text: str, error: Exception) -> list[Message]:
    """Append the model's bad reply plus the parse error, per T-AG-01."""

    return [
        *messages,
        {"role": "assistant", "content": previous_text or ""},
        {
            "role": "user",
            "content": (
                "Your previous reply could not be parsed as a single JSON object: "
                f"{error}. Reply again with ONLY one valid JSON object and no prose."
            ),
        },
    ]


class HTTPProvider:
    """Base class for adapters that talk JSON over HTTP."""

    name = "http"
    _endpoint = ""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: SleepFn | None = None,
        max_retries: int | None = None,
        backoff: float | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        input_cost_per_1k: float = 0.0,
        output_cost_per_1k: float = 0.0,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._max_retries = max_retries
        self._backoff = backoff
        self._default_timeout = timeout
        self._input_cost_per_1k = input_cost_per_1k
        self._output_cost_per_1k = output_cost_per_1k
        self._reasoning_effort = reasoning_effort

    # -- hooks -----------------------------------------------------------
    def _headers(self) -> dict[str, str]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _build_request(
        self,
        messages: Sequence[Message],
        response_format: dict[str, Any] | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: ReasoningEffort | None,
    ) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _parse(self, body: dict[str, Any]) -> _Parsed:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- shared plumbing -------------------------------------------------
    def _usage(self, input_tokens: int, output_tokens: int) -> Usage:
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd_estimate=estimate_cost(
                input_tokens,
                output_tokens,
                input_per_1k=self._input_cost_per_1k,
                output_per_1k=self._output_cost_per_1k,
            ),
        )

    async def _request(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "headers": self._headers(),
            "payload": payload,
            "timeout": timeout,
            "retries": self._max_retries,
            "backoff": self._backoff,
            "sleep": self._sleep,
            "error_prefix": f"{self.name} request",
        }
        if self._client is not None:
            return await post_json(self._client, self._endpoint, **kwargs)
        async with httpx.AsyncClient() as client:
            return await post_json(client, self._endpoint, **kwargs)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        response_format: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = DEFAULT_TIMEOUT,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> Completion:
        timeout = timeout or self._default_timeout
        effective_reasoning_effort = reasoning_effort or self._reasoning_effort
        payload = self._build_request(messages, response_format, max_tokens, temperature, effective_reasoning_effort)
        parsed = self._parse(await self._request(payload, timeout))
        if response_format is None:
            return Completion(text=parsed.text, usage=parsed.usage, raw_id=parsed.raw_id)
        try:
            data = extract_json(parsed.text)
        except ValueError as first:
            retry_messages = build_retry_messages(messages, parsed.text, first)
            retry_payload = self._build_request(
                retry_messages,
                response_format,
                max_tokens,
                temperature,
                effective_reasoning_effort,
            )
            second = self._parse(await self._request(retry_payload, timeout))
            try:
                data = extract_json(second.text)
            except ValueError as second_error:
                raise LLMOutputError(
                    f"{self.name}: structured output unparsable after one retry ({second_error})"
                ) from second_error
            return Completion(
                text=second.text,
                json=data,
                usage=parsed.usage + second.usage,
                raw_id=second.raw_id,
            )
        return Completion(text=parsed.text, json=data, usage=parsed.usage, raw_id=parsed.raw_id)
