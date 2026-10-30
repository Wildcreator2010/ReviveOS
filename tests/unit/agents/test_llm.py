"""T-AG-01: three real HTTP adapters, custom base_url, retry contract, fake replay."""

from __future__ import annotations

import json
import re

import httpx
import pytest
from revive_agents.llm import (
    AnthropicProvider,
    FakeProvider,
    LLMError,
    LLMOutputError,
    OpenAIProvider,
    from_config,
)
from revive_agents.llm.openai_adapter import to_openai_response_format

_SK_PATTERN = re.compile(r"sk-[A-Za-z0-9]{20,}")


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def openai_body(content: str, *, prompt: int = 3, completion: int = 2) -> dict:
    return {
        "id": "resp-1",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


# ---------------------------------------------------------------- OpenAI/custom
async def test_openai_custom_base_url_and_request_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=openai_body('{"ok": true}'))

    client = mock_client(handler)
    provider = OpenAIProvider(
        "secret-key", "my-model", "https://llm.internal/v1/", provider_name="custom", client=client
    )
    completion = await provider.complete(
        [{"role": "user", "content": "hi"}],
        response_format={"title": "payload", "type": "object", "properties": {}},
    )
    await client.aclose()

    assert captured["url"] == "https://llm.internal/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer secret-key"
    assert captured["body"]["model"] == "my-model"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["body"]["response_format"]["json_schema"]["name"] == "payload"
    assert completion.text == '{"ok": true}'
    assert completion.json == {"ok": True}
    assert completion.usage.input_tokens == 3
    assert completion.usage.output_tokens == 2
    assert completion.raw_id == "resp-1"


async def test_openai_default_base_url_is_openai():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=openai_body("ok"))

    client = mock_client(handler)
    provider = OpenAIProvider("k", "gpt-x", client=client)
    await provider.complete([{"role": "user", "content": "x"}])
    await client.aclose()
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"


def test_custom_provider_rejects_plaintext_non_loopback_base_url():
    with pytest.raises(LLMError):
        OpenAIProvider("k", "m", "http://llm.example/v1", provider_name="custom")


def test_custom_provider_allows_loopback_http_base_url():
    provider = OpenAIProvider("k", "m", "http://127.0.0.1:8000/v1", provider_name="custom")
    assert provider.base_url == "http://127.0.0.1:8000/v1"


async def test_oversized_provider_response_is_rejected(monkeypatch):
    monkeypatch.setattr("revive_agents.llm._http.MAX_RESPONSE_BYTES", 10)
    client = mock_client(lambda request: httpx.Response(200, json=openai_body("x" * 100)))
    provider = OpenAIProvider("k", "m", client=client)
    with pytest.raises(LLMError, match="size"):
        await provider.complete([{"role": "user", "content": "x"}])
    await client.aclose()


async def test_openai_reasoning_effort_is_forwarded():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=openai_body("ok"))

    client = mock_client(handler)
    provider = OpenAIProvider("k", "gpt-6.1-sol", client=client)
    await provider.complete([{"role": "user", "content": "think"}], reasoning_effort="high")
    await client.aclose()
    assert captured["body"]["reasoning_effort"] == "high"


def test_response_format_wrapper_passthrough():
    already = {"type": "json_object"}
    assert to_openai_response_format(already) == already
    wrapped = to_openai_response_format({"title": "t", "type": "object"})
    assert wrapped["type"] == "json_schema"
    assert wrapped["json_schema"]["strict"] is True


# ------------------------------------------------------------------- Anthropic
async def test_anthropic_request_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg-1",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        )

    client = mock_client(handler)
    provider = AnthropicProvider("a-key", "claude-x", client=client)
    completion = await provider.complete([{"role": "system", "content": "be brief"}, {"role": "user", "content": "u"}])
    await client.aclose()

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "a-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["system"] == "be brief"
    assert captured["body"]["messages"] == [{"role": "user", "content": "u"}]
    assert "reasoning_effort" not in captured["body"]
    assert completion.text == "ok"
    assert completion.usage.input_tokens == 1


# ------------------------------------------------------- structured output retry
async def test_structured_output_retries_once_then_succeeds():
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, json=openai_body("not json at all"))
        return httpx.Response(200, json=openai_body('{"answer": 42}'))

    client = mock_client(handler)
    provider = OpenAIProvider("k", "m", client=client)
    completion = await provider.complete(
        [{"role": "user", "content": "go"}],
        response_format={"title": "answer", "type": "object"},
    )
    await client.aclose()

    assert len(requests) == 2
    assert completion.json == {"answer": 42}
    retry_messages = requests[1]["messages"]
    assert retry_messages[-2]["role"] == "assistant"
    assert "could not be parsed" in retry_messages[-1]["content"]


async def test_structured_output_fails_after_one_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=openai_body("still not json"))

    client = mock_client(handler)
    provider = OpenAIProvider("k", "m", client=client)
    with pytest.raises(LLMOutputError):
        await provider.complete(
            [{"role": "user", "content": "go"}],
            response_format={"title": "answer", "type": "object"},
        )
    await client.aclose()
    assert calls["n"] == 2


# ---------------------------------------------------- transport retry / timeout
async def test_transport_retry_with_backoff_on_5xx():
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=openai_body("recovered"))

    client = mock_client(handler)
    provider = OpenAIProvider("k", "m", client=client, sleep=sleeper, backoff=0.25, max_retries=2)
    completion = await provider.complete([{"role": "user", "content": "x"}])
    await client.aclose()

    assert state["n"] == 2
    assert delays == [0.25]
    assert completion.text == "recovered"


async def test_timeout_is_retried():
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ReadTimeout("too slow")
        return httpx.Response(200, json=openai_body("late but fine"))

    async def sleeper(delay: float) -> None:
        return None

    client = mock_client(handler)
    provider = OpenAIProvider("k", "m", client=client, sleep=sleeper, max_retries=1)
    completion = await provider.complete([{"role": "user", "content": "x"}])
    await client.aclose()
    assert state["n"] == 2
    assert completion.text == "late but fine"


# ----------------------------------------------------------------------- factory
def test_missing_api_key_error_never_contains_key():
    with pytest.raises(LLMError) as excinfo:
        OpenAIProvider(None, "m")
    message = str(excinfo.value)
    assert "REVIVE_LLM__API_KEY" in message
    assert not _SK_PATTERN.search(message)


def test_factory_defaults_to_fake():
    assert isinstance(from_config(), FakeProvider)


def test_factory_selects_anthropic_from_config():
    provider = from_config(
        {
            "REVIVE_LLM__PROVIDER": "anthropic",
            "REVIVE_LLM__API_KEY": "k",
            "REVIVE_LLM__MODEL": "m",
        }
    )
    assert isinstance(provider, AnthropicProvider)


def test_factory_custom_requires_base_url():
    with pytest.raises(LLMError) as excinfo:
        from_config(
            {
                "REVIVE_LLM__PROVIDER": "custom",
                "REVIVE_LLM__API_KEY": "k",
                "REVIVE_LLM__MODEL": "m",
            }
        )
    assert "REVIVE_LLM__BASE_URL" in str(excinfo.value)


def test_factory_rejects_invalid_reasoning_effort(monkeypatch):
    monkeypatch.setenv("REVIVE_LLM__REASONING_EFFORT", "extreme")
    with pytest.raises(LLMError, match="REASONING_EFFORT"):
        from_config(
            {
                "REVIVE_LLM__PROVIDER": "openai",
                "REVIVE_LLM__API_KEY": "k",
                "REVIVE_LLM__MODEL": "gpt-6.1-sol",
            }
        )


def test_factory_rejects_unknown_provider():
    with pytest.raises(LLMError):
        from_config({"REVIVE_LLM__PROVIDER": "martian"})


# -------------------------------------------------------------------- fake replay
async def test_fake_replay_is_hash_keyed_and_offline():
    messages = [{"role": "user", "content": "ping"}]
    provider = FakeProvider()
    provider.add(messages, {"text": "pong", "usage": {"input_tokens": 1, "output_tokens": 1}})

    first = await provider.complete(messages)
    second = await provider.complete(messages)
    assert first.text == "pong"
    assert second.text == "pong"
    assert first.usage.input_tokens == 1

    with pytest.raises(LLMOutputError):
        await provider.complete([{"role": "user", "content": "unrecorded"}])


async def test_fake_structured_output_parses_text_reply():
    messages = [{"role": "user", "content": "give json"}]
    provider = FakeProvider({FakeProvider.prompt_hash(messages): '{"ok": true}'})
    completion = await provider.complete(messages, response_format={"type": "object"})
    assert completion.json == {"ok": True}
