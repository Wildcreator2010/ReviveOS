"""Anthropic Messages API HTTP adapter.

Uses the documented 'POST /v1/messages' shape with 'x-api-key' auth.  Anthropic
has no response_format parameter, so when structured output is requested the
JSON schema is appended to the system prompt and the same one-retry parse
contract from the shared base applies.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ._adapter_base import HTTPProvider, _Parsed
from ._http import validate_base_url
from .base import LLMError, Message, ReasoningEffort

DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(HTTPProvider):
    """Real HTTP provider for the Anthropic Messages API."""

    def __init__(
        self,
        api_key: str | None,
        model: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        if not api_key:
            raise LLMError("REVIVE_LLM__API_KEY is required for the anthropic provider")
        if not model:
            raise LLMError("REVIVE_LLM__MODEL is required for the anthropic provider")
        super().__init__(**kwargs)
        self.api_key = api_key
        self.model = model
        resolved_base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        validate_base_url(resolved_base)
        self.base_url = resolved_base
        self._endpoint = f"{self.base_url}/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    @staticmethod
    def _split_system(
        messages: Sequence[Message],
    ) -> tuple[list[str], list[dict[str, str]]]:
        system_parts: list[str] = []
        convo: list[dict[str, str]] = []
        for message in messages:
            role = message.get("role")
            content = str(message.get("content", ""))
            if role == "system":
                system_parts.append(content)
            elif role in ("user", "assistant"):
                convo.append({"role": role, "content": content})
            else:
                convo.append({"role": "user", "content": content})
        return system_parts, convo

    def _build_request(
        self,
        messages: Sequence[Message],
        response_format: dict[str, Any] | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> dict[str, Any]:
        system_parts, convo = self._split_system(messages)
        if response_format is not None:
            system_parts.append(
                "Respond with a single JSON object conforming to this JSON schema: "
                + json.dumps(response_format, sort_keys=True, ensure_ascii=False)
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": convo,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        return payload

    def _parse(self, body: dict[str, Any]) -> _Parsed:
        blocks = body.get("content") or []
        text = "".join(
            block.get("text", "") for block in blocks if isinstance(block, dict) and block.get("type", "text") == "text"
        )
        raw_usage = body.get("usage") or {}
        usage = self._usage(
            int(raw_usage.get("input_tokens", 0) or 0),
            int(raw_usage.get("output_tokens", 0) or 0),
        )
        return _Parsed(text=text, usage=usage, raw_id=str(body.get("id", "")))
