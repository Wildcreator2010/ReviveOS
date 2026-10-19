"""OpenAI and OpenAI-compatible ('custom') HTTP adapter.

The 'custom' provider is the exact same code path with a user-supplied
'REVIVE_LLM__BASE_URL' pointing at any OpenAI-compatible endpoint; only the
base URL differs, and that is asserted by the unit tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ._adapter_base import HTTPProvider, _Parsed
from .base import LLMError, Message, ReasoningEffort

DEFAULT_BASE_URL = "https://api.openai.com/v1"

_OPENAI_WRAPPER_TYPES = frozenset({"json_object", "json_schema", "text"})


def to_openai_response_format(response_format: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw JSON Schema into the OpenAI structured-output envelope."""

    if not isinstance(response_format, dict):
        raise LLMError("response_format must be a JSON Schema object")
    if response_format.get("type") in _OPENAI_WRAPPER_TYPES:
        return dict(response_format)
    schema = {k: v for k, v in response_format.items() if k != "title"}
    if not schema:
        schema = {"type": "object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": str(response_format.get("title") or "output"),
            "schema": schema,
            "strict": True,
        },
    }


class OpenAIProvider(HTTPProvider):
    """Real HTTP provider for api.openai.com and OpenAI-compatible gateways."""

    def __init__(
        self,
        api_key: str | None,
        model: str | None = None,
        base_url: str | None = None,
        *,
        provider_name: str = "openai",
        **kwargs: Any,
    ) -> None:
        if not api_key:
            raise LLMError(f"REVIVE_LLM__API_KEY is required for the {provider_name} provider")
        if not model:
            raise LLMError(f"REVIVE_LLM__MODEL is required for the {provider_name} provider")
        super().__init__(**kwargs)
        self.name = provider_name
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._endpoint = f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_request(
        self,
        messages: Sequence[Message],
        response_format: dict[str, Any] | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(m) for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = to_openai_response_format(response_format)
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        return payload

    def _parse(self, body: dict[str, Any]) -> _Parsed:
        choices = body.get("choices") or []
        if not choices:
            raise LLMError("openai-compatible response contained no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        text = content or ""
        raw_usage = body.get("usage") or {}
        usage = self._usage(
            int(raw_usage.get("prompt_tokens", 0) or 0),
            int(raw_usage.get("completion_tokens", 0) or 0),
        )
        return _Parsed(text=text, usage=usage, raw_id=str(body.get("id", "")))
