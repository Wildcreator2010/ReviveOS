"""Public surface of the LLM provider layer.

Import the protocol, value objects and the factory from here; never import a
vendor SDK in node/supervisor code.
"""

from .anthropic_adapter import AnthropicProvider
from .base import (
    BudgetExceeded,
    Completion,
    LLMError,
    LLMOutputError,
    LLMProvider,
    Message,
    ReasoningEffort,
    Usage,
    estimate_cost,
    extract_json,
)
from .factory import SUPPORTED_PROVIDERS, ConfigSource, from_config
from .fake import FakeProvider
from .openai_adapter import OpenAIProvider, to_openai_response_format

__all__ = [
    "AnthropicProvider",
    "BudgetExceeded",
    "Completion",
    "ConfigSource",
    "FakeProvider",
    "LLMError",
    "LLMOutputError",
    "LLMProvider",
    "Message",
    "OpenAIProvider",
    "ReasoningEffort",
    "SUPPORTED_PROVIDERS",
    "Usage",
    "estimate_cost",
    "extract_json",
    "from_config",
    "to_openai_response_format",
]
