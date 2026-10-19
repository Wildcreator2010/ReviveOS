"""LLM provider protocol, value objects and shared parsing helpers.

This is the single LLM egress point for ReviveOS.  Nothing below this package
may import a vendor SDK directly: adapters are constructed exclusively through
'revive_agents.llm.factory'.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Message = dict[str, str]
ReasoningEffort = Literal["low", "medium", "high"]

__all__ = [
    "Message",
    "Usage",
    "Completion",
    "LLMError",
    "LLMOutputError",
    "BudgetExceeded",
    "LLMProvider",
    "extract_json",
    "estimate_cost",
    "ReasoningEffort",
]


@dataclass(frozen=True)
class Usage:
    """Token usage and a provider-supplied cost estimate (never guessed)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd_estimate: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd_estimate=self.cost_usd_estimate + other.cost_usd_estimate,
        )

    @classmethod
    def coerce(cls, value: Any) -> Usage:
        if isinstance(value, Usage):
            return value
        if value is None:
            return cls()
        if isinstance(value, dict):
            return cls(
                input_tokens=int(value.get("input_tokens", value.get("prompt_tokens", 0)) or 0),
                output_tokens=int(value.get("output_tokens", value.get("completion_tokens", 0)) or 0),
                cost_usd_estimate=float(value.get("cost_usd_estimate", 0.0) or 0.0),
            )
        if isinstance(value, (list, tuple)):
            padded = list(value) + [0, 0, 0.0]
            return cls(int(padded[0] or 0), int(padded[1] or 0), float(padded[2] or 0.0))
        raise TypeError(f"cannot coerce {type(value)!r} to Usage")


@dataclass(frozen=True)
class Completion:
    text: str = ""
    json: dict[str, Any] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    raw_id: str = ""


class LLMError(RuntimeError):
    """Any LLM transport/configuration/provider failure."""


class LLMOutputError(LLMError):
    """Structured output could not be parsed after the single mandated retry."""


class BudgetExceeded(LLMError):
    """The per-job LLM cost budget (REVIVE_LLM__JOB_BUDGET_USD) was exhausted."""


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        response_format: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 30.0,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> Completion: ...


_BACKTICK = chr(96)
_FENCE_RE = re.compile(
    r"^\s*" + _BACKTICK * 3 + r"(?:json)?\s*(.*?)\s*" + _BACKTICK * 3 + r"\s*$",
    re.DOTALL,
)


def extract_json(text: str | None) -> dict[str, Any]:
    """Best-effort extraction of a single JSON object from a model reply.

    Raises ValueError (never a vendor exception) so adapters can feed the
    message back on the one mandated structured-output retry.
    """

    if not text or not text.strip():
        raise ValueError("empty response")
    candidate = text.strip()
    fence = _FENCE_RE.match(candidate)
    if fence:
        candidate = fence.group(1).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        starts = [i for i in (candidate.find("{"), candidate.find("[")) if i >= 0]
        start = min(starts) if starts else -1
        end = max(candidate.rfind("}"), candidate.rfind("]"))
        if start >= 0 and end > start:
            try:
                value = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                raise ValueError(f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc
        else:
            raise ValueError(f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON response must be an object")
    return value


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    input_per_1k: float = 0.0,
    output_per_1k: float = 0.0,
) -> float:
    """Cost estimate from explicitly configured rates.

    No vendor/model price is hard-coded in business code; deployments set
    REVIVE_LLM__INPUT_COST_PER_1K / REVIVE_LLM__OUTPUT_COST_PER_1K (or pass
    rates to the adapter).  Unconfigured rates yield 0.0.
    """

    return round((input_tokens / 1000.0) * input_per_1k + (output_tokens / 1000.0) * output_per_1k, 8)
