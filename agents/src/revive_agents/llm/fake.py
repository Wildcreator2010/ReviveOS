"""Replay-only fake LLM provider used by every unit test.

Responses are keyed by a sha256 hash over the exact message list, so a test
that records one prompt can never accidentally serve another and golden tests
stay stable.  The fake never opens a socket.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Any, cast

from .base import (
    Completion,
    LLMOutputError,
    Message,
    Usage,
    extract_json,
)

ReplayValue = Completion | dict[str, Any] | str | Sequence[Any] | Callable[..., Any]


class FakeProvider:
    """Deterministic prompt-hash replay provider (no network, ever)."""

    def __init__(
        self,
        recordings: dict[str, ReplayValue] | None = None,
        *,
        responder: ReplayValue | None = None,
    ) -> None:
        self.recordings: dict[str, ReplayValue] = dict(recordings or {})
        self.responder = list(responder) if isinstance(responder, tuple) else responder
        self.calls: list[list[Message]] = []

    # -- recording helpers ----------------------------------------------
    @staticmethod
    def prompt_hash(messages: Sequence[Message]) -> str:
        canonical = [dict(m) for m in messages]
        blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @classmethod
    def fingerprint(cls, messages: Sequence[Message]) -> str:
        return cls.prompt_hash(messages)[:12]

    def add(self, messages: Sequence[Message], value: ReplayValue) -> str:
        key = self.prompt_hash(messages)
        self.recordings[key] = value
        return key

    # -- normalisation ---------------------------------------------------
    @staticmethod
    def _normalise(value: ReplayValue) -> Completion:
        if isinstance(value, Completion):
            return value
        if isinstance(value, dict):
            keys = set(value.keys())
            is_envelope = "json" in keys or "usage" in keys or "raw_id" in keys or (keys <= {"text"} and "text" in keys)
            if not is_envelope:
                # A bare payload is treated as the structured body itself.
                return Completion(
                    text=json.dumps(value, sort_keys=True, ensure_ascii=False),
                    json=dict(value),
                    usage=Usage(),
                    raw_id="fake",
                )
            text = str(value.get("text", "") or "")
            data = value.get("json")
            if data is None:
                data = {}
                if text:
                    try:
                        data = extract_json(text)
                    except ValueError:
                        data = {}
            return Completion(
                text=text,
                json=dict(data),
                usage=Usage.coerce(value.get("usage")),
                raw_id=str(value.get("raw_id", "fake")),
            )
        if isinstance(value, str):
            parsed: dict[str, Any] = {}
            try:
                parsed = extract_json(value)
            except ValueError:
                parsed = {}
            return Completion(text=value, json=parsed, usage=Usage(), raw_id="fake")
        if isinstance(value, (list, tuple)):
            return Completion(json={}, usage=Usage.coerce(value), raw_id="fake")
        raise TypeError(f"unsupported fake replay value: {type(value)!r}")

    def _dispatch(self, key: str, messages: Sequence[Message]) -> ReplayValue | None:
        responder = self.responder
        if responder is None:
            return self.recordings.get(key)
        if callable(responder):
            return cast(ReplayValue, responder(messages))
        if isinstance(responder, list):
            return cast(ReplayValue | None, responder.pop(0)) if responder else None
        return cast(ReplayValue, responder)

    # -- provider protocol ----------------------------------------------
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        response_format: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 30.0,
        reasoning_effort: str | None = None,
    ) -> Completion:
        self.calls.append([dict(m) for m in messages])
        key = self.prompt_hash(messages)
        value = self._dispatch(key, messages)
        if value is None:
            raise LLMOutputError(
                f"no fake replay recorded for prompt {key[:12]}; call FakeProvider.add(messages, completion)"
            )
        completion = self._normalise(value)
        if response_format is not None and not completion.json and completion.text:
            try:
                parsed = extract_json(completion.text)
            except ValueError as exc:
                raise LLMOutputError(f"fake replay for prompt {key[:12]} is not valid JSON: {exc}") from exc
            completion = Completion(
                text=completion.text,
                json=parsed,
                usage=completion.usage,
                raw_id=completion.raw_id,
            )
        return completion
