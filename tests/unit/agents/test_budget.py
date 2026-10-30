"""T-AG-07: per-job budget guard and hash-only LLM tracing.

check_global_rules: allow-secret-file -- this module feeds key-shaped strings to
scrub() and Tracer on purpose to prove redaction. They are assembled at runtime
from synthetic alphabet runs, never credentials; real keys stay forbidden.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from revive_agents.budget import BudgetedProvider, JobBudget, default_limit
from revive_agents.llm import BudgetExceeded, FakeProvider, Usage
from revive_agents.observability import (
    LLMCallRecord,
    TracedProvider,
    Tracer,
    content_hash,
    scrub,
)

# Assembled at runtime so the source contains no literal key-shaped string.
SECRET = "sk-" + "a" * 24
MESSAGE_WITH_SECRET = "key " + SECRET


class RecordingPort:
    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    async def record(self, record: LLMCallRecord) -> None:
        self.records.append(record)


def test_default_limit_comes_from_env(monkeypatch):
    monkeypatch.setenv("REVIVE_LLM__JOB_BUDGET_USD", "1.25")
    assert default_limit() == 1.25
    assert JobBudget().limit == 1.25


def test_charge_crossing_limit_raises():
    budget = JobBudget(limit=0.5)
    budget.charge(Usage(cost_usd_estimate=0.3))
    with pytest.raises(BudgetExceeded):
        budget.charge(Usage(cost_usd_estimate=0.3))


async def test_budget_enforces_a_call_cap_when_cost_rates_are_zero():
    provider = FakeProvider(
        responder=[
            {"json": {"ok": 1}, "usage": {}},
            {"json": {"ok": 2}, "usage": {}},
            {"json": {"ok": 3}, "usage": {}},
        ]
    )
    guarded = BudgetedProvider(provider, JobBudget(limit=10.0, max_calls=2))

    await guarded.complete([{"role": "user", "content": "a"}])
    await guarded.complete([{"role": "user", "content": "b"}])
    with pytest.raises(BudgetExceeded):
        await guarded.complete([{"role": "user", "content": "c"}])
    assert len(provider.calls) == 2


async def test_budgeted_provider_fails_at_the_threshold():
    provider = FakeProvider(
        responder=[
            {"json": {"ok": 1}, "usage": {"cost_usd_estimate": 0.3}},
            {"json": {"ok": 2}, "usage": {"cost_usd_estimate": 0.3}},
        ]
    )
    budget = JobBudget(limit=0.5)
    guarded = BudgetedProvider(provider, budget)

    first = await guarded.complete([{"role": "user", "content": "a"}])
    assert first.json == {"ok": 1}
    with pytest.raises(BudgetExceeded):
        await guarded.complete([{"role": "user", "content": "b"}])
    assert budget.spent == pytest.approx(0.6)
    assert len(provider.calls) == 2


async def test_traced_provider_records_hashes_only():
    port = RecordingPort()
    tracer = Tracer(port)
    inner = FakeProvider(
        responder=lambda messages: {
            "text": "hello",
            "usage": {"input_tokens": 2, "output_tokens": 1, "cost_usd_estimate": 0.01},
        }
    )
    provider = TracedProvider(
        inner,
        tracer,
        job_id="job-1",
        node="archaeologist",
        prompt_name="archaeologist",
        prompt_version="v1",
        model="m",
    )
    completion = await provider.complete([{"role": "user", "content": "secret prompt"}])

    assert completion.text == "hello"
    assert len(port.records) == 1
    record = port.records[0]
    expected_request = '[{"content": "secret prompt", "role": "user"}]'
    assert record.request_hash == content_hash(expected_request)
    assert record.response_hash == content_hash("hello")
    assert record.cost_usd_estimate == pytest.approx(0.01)
    assert "secret prompt" not in str(record.to_dict())


def test_tracing_source_declares_response_hash():
    source = Path("agents/src/revive_agents/observability/tracing.py").read_text(encoding="utf-8")
    assert "response_hash" in source


def test_scrub_redacts_secret_shapes():
    scrubbed = scrub("Authorization: Bearer " + SECRET)
    assert SECRET not in scrubbed
    assert "[REDACTED]" in scrubbed


async def test_debug_mode_returns_scrubbed_full_text():
    port = RecordingPort()
    tracer = Tracer(port, debug=True)
    inner = FakeProvider(responder=lambda messages: {"text": "ok", "usage": {}})
    provider = TracedProvider(inner, tracer, job_id="j", node="n")
    await provider.complete([{"role": "user", "content": MESSAGE_WITH_SECRET}])
    record = port.records[0]
    payload = tracer.full_text(record, '[{"content": "' + MESSAGE_WITH_SECRET + '"}]', "ok")
    assert payload is not None
    assert SECRET not in payload["request"]
    assert "[REDACTED]" in payload["request"]


def test_debug_disabled_keeps_full_text_out():
    tracer = Tracer(None, debug=False)
    record = LLMCallRecord(
        job_id="j",
        node="n",
        prompt_name="",
        prompt_version="",
        model="",
        request_hash="",
        response_hash="",
        latency_ms=0.0,
    )
    assert tracer.full_text(record, "a", "b") is None
