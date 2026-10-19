"""T-AG-03: evidence-bound archaeologist (correct / hallucination / malformed)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from revive_agents.llm import FakeProvider
from revive_agents.nodes import archaeologist

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "schemas" / "environment-genome.schema.json").read_text(encoding="utf-8")
)

EVIDENCE = [
    {
        "id": "e1",
        "source_kind": "doc",
        "reference": "README.md#runtime",
        "note": "python 3.7 required",
    },
    {"id": "e2", "source_kind": "manifest_file", "reference": "setup.py"},
]


def genome() -> dict:
    return {
        "python": {
            "version": "2.7",
            "confidence": 0.3,
            "evidence": [{"source_kind": "manifest_file", "reference": "setup.py"}],
        },
        "os": {
            "image": "python:2.7",
            "confidence": 0.6,
            "evidence": [{"source_kind": "ci_config", "reference": ".travis.yml"}],
        },
        "dependencies": [
            {
                "name": "requests",
                "version": "2.5.0",
                "source": "requirements.txt",
                "confidence": 0.5,
                "evidence": [],
            }
        ],
        "cuda": {"confidence": 0.0, "evidence": []},
        "system_libs": [{"confidence": 0.4, "evidence": []}],
        "overall_confidence": 0.45,
    }


def test_fixture_genome_is_schema_valid():
    jsonschema.validate(genome(), SCHEMA)


async def test_correct_reinforcement_is_merged_and_schema_valid():
    payload = {
        "updates": {
            "python": {
                "confidence": 0.95,
                "evidence_ids": ["e1"],
                "version": "3.7",
                "llm_reason": "README states python 3.7 is required",
            }
        }
    }
    provider = FakeProvider(responder=lambda messages: payload)
    outcome = await archaeologist(genome(), ["python", "overall_confidence"], EVIDENCE, provider)

    assert outcome.genome["python"]["confidence"] == 0.95
    assert outcome.genome["python"]["version"] == "3.7"
    assert len(outcome.genome["python"]["evidence"]) == 2
    assert outcome.modifications[0]["llm_reason"]
    assert outcome.modifications[0]["evidence_ids"] == ["e1"]
    assert outcome.warnings == []
    jsonschema.validate(outcome.genome, SCHEMA)


async def test_hallucinated_evidence_is_rejected():
    payload = {
        "updates": {
            "python": {
                "confidence": 0.99,
                "evidence_ids": ["ghost-42"],
                "version": "3.11",
                "llm_reason": "invented evidence",
            }
        }
    }
    provider = FakeProvider(responder=lambda messages: payload)
    original = genome()
    outcome = await archaeologist(original, ["python"], EVIDENCE, provider)

    assert outcome.genome["python"]["confidence"] == 0.3
    assert outcome.genome["python"]["version"] == "2.7"
    assert len(outcome.genome["python"]["evidence"]) == 1
    assert outcome.modifications == []
    assert any("hallucinated" in warning for warning in outcome.warnings)
    jsonschema.validate(outcome.genome, SCHEMA)


async def test_malformed_json_returns_original_genome():
    provider = FakeProvider(responder=lambda messages: "this is definitely not json")
    original = genome()
    outcome = await archaeologist(original, ["python"], EVIDENCE, provider)

    assert outcome.genome == original
    assert outcome.modifications == []
    assert outcome.warnings and "retained" in outcome.warnings[0]
    assert provider.calls, "the node should have attempted an LLM call"


async def test_confidence_never_decreases_and_evidence_is_appended():
    payload = {
        "updates": {
            "python": {
                "confidence": 0.1,
                "evidence_ids": ["e2"],
                "llm_reason": "downgrade attempt",
            }
        }
    }
    provider = FakeProvider(responder=lambda messages: payload)
    outcome = await archaeologist(genome(), ["python"], EVIDENCE, provider)

    assert outcome.genome["python"]["confidence"] == 0.3
    assert len(outcome.genome["python"]["evidence"]) == 2
    jsonschema.validate(outcome.genome, SCHEMA)


async def test_unknown_field_is_rejected():
    payload = {"updates": {"ruby": {"confidence": 1.0, "evidence_ids": ["e1"], "llm_reason": "x"}}}
    provider = FakeProvider(responder=lambda messages: payload)
    outcome = await archaeologist(genome(), ["python"], EVIDENCE, provider)
    assert "ruby" not in outcome.genome
    assert any("unknown genome field" in warning for warning in outcome.warnings)


async def test_missing_reason_is_rejected():
    payload = {"updates": {"python": {"confidence": 0.9, "evidence_ids": ["e1"]}}}
    provider = FakeProvider(responder=lambda messages: payload)
    outcome = await archaeologist(genome(), ["python"], EVIDENCE, provider)
    assert outcome.genome["python"]["confidence"] == 0.3
    assert any("llm_reason" in warning for warning in outcome.warnings)
