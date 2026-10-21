"""Provider factory: the only sanctioned construction path for LLM adapters.

Business code (nodes, supervisor) must never import a vendor SDK or instantiate
an adapter directly; it calls 'from_config' and receives an 'LLMProvider'.
Credentials are read only from 'REVIVE_LLM__*' environment variables (or an
explicit config mapping); no key is ever written to code or logs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ._http import env_float
from .anthropic_adapter import AnthropicProvider
from .base import LLMError, LLMProvider
from .fake import FakeProvider
from .openai_adapter import OpenAIProvider

SUPPORTED_PROVIDERS = ("openai", "anthropic", "custom", "fake")
SUPPORTED_REASONING_EFFORTS = frozenset({"low", "medium", "high"})


def _canon(key: str) -> str:
    normalised = str(key).strip().upper().replace(".", "__")
    parts = [part for part in normalised.split("__") if part]
    normalised = "_".join(parts)
    if normalised.startswith("REVIVE_"):
        normalised = normalised[len("REVIVE_") :]
    return normalised


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _flatten(f"{prefix}__{key}" if prefix else str(key), item, out)
    else:
        out[_canon(prefix)] = value


def _config_values(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, Mapping):
        values: dict[str, Any] = {}
        _flatten("", config, values)
        return values
    dump = getattr(config, "model_dump", None)
    if callable(dump):
        values = {}
        _flatten("", dump(), values)
        return values
    values = {}
    _flatten("", vars(config), values)
    return values


class ConfigSource:
    """Looks up canonical keys in the supplied config, falling back to env."""

    def __init__(self, config: Any = None) -> None:
        self._values = _config_values(config)

    def get(self, key: str, default: Any = None) -> Any:
        canonical = _canon(key)
        if canonical in self._values and self._values[canonical] not in (None, ""):
            return self._values[canonical]
        env_names = ["REVIVE_" + canonical, canonical]
        if canonical.startswith("LLM_"):
            env_names.insert(0, "REVIVE_LLM__" + canonical[len("LLM_") :])
        value = next((os.getenv(name) for name in env_names if os.getenv(name) is not None), None)
        return default if value is None or value == "" else value


def from_config(config: Any = None) -> LLMProvider:
    """Instantiate the provider selected by 'REVIVE_LLM__PROVIDER'."""

    source = ConfigSource(config)
    provider = str(source.get("LLM_PROVIDER", "fake")).strip().lower()
    if provider == "fake":
        return FakeProvider()
    api_key = source.get("LLM_API_KEY")
    model = source.get("LLM_MODEL")
    base_url = source.get("LLM_BASE_URL")
    reasoning_effort = source.get("LLM_REASONING_EFFORT")
    if reasoning_effort is not None:
        reasoning_effort = str(reasoning_effort).strip().lower()
        if reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
            raise LLMError("REVIVE_LLM__REASONING_EFFORT must be one of: low, medium, high")
    common: dict[str, Any] = {
        "input_cost_per_1k": env_float("REVIVE_LLM__INPUT_COST_PER_1K", 0.0),
        "output_cost_per_1k": env_float("REVIVE_LLM__OUTPUT_COST_PER_1K", 0.0),
        "reasoning_effort": reasoning_effort,
    }
    if provider == "openai":
        return OpenAIProvider(api_key, model, base_url or None, **common)
    if provider == "anthropic":
        return AnthropicProvider(api_key, model, base_url or None, **common)
    if provider == "custom":
        if not base_url:
            raise LLMError("REVIVE_LLM__BASE_URL is required when REVIVE_LLM__PROVIDER=custom")
        return OpenAIProvider(api_key, model, base_url, provider_name="custom", **common)
    raise LLMError(f"unsupported REVIVE_LLM__PROVIDER {provider!r}; expected one of {', '.join(SUPPORTED_PROVIDERS)}")


def from_settings(settings: Mapping[str, Any]) -> LLMProvider:
    """Build a provider from the admin-managed runtime_settings document."""

    return from_config(
        {
            "LLM_PROVIDER": settings.get("provider"),
            "LLM_BASE_URL": settings.get("base_url"),
            "LLM_MODEL": settings.get("model"),
            "LLM_API_KEY": settings.get("api_key"),
            "LLM_REASONING_EFFORT": settings.get("reasoning_effort"),
        }
    )
