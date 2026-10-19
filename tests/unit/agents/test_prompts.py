"""T-AG-02: prompt registry, variable validation and golden hash stability."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from revive_agents.prompts import (
    PromptVarsError,
    list_prompts,
    message_hash,
    output_contract,
    render,
    required_vars,
)

GOLDEN = Path(__file__).parent / "golden" / "prompt_hashes.json"

GOLDEN_RENDERS = {
    "archaeologist": ("archaeologist", {"fields": "python, os", "evidence": "[]"}),
    "repairer": (
        "repairer",
        {
            "error_fact": "{}",
            "manifest": "[]",
            "prior_attempts": "[]",
            "memory_cases": "[]",
        },
    ),
    "validator": ("validator", {"context": "x"}),
    "behavior": (
        "behavior",
        {"source_tree": "{}", "readme": "r", "tests_dir": "None", "examples_dir": "None"},
    ),
}


def test_render_substitutes_variables():
    messages = render("validator", context="hello world")
    assert messages[0]["role"] == "system"
    assert "hello world" in messages[0]["content"]


def test_render_preserves_literal_json_braces():
    messages = render("archaeologist", fields="python", evidence="[]")
    assert '{"updates"' in messages[0]["content"]


def test_missing_variables_are_listed():
    with pytest.raises(PromptVarsError) as excinfo:
        render("validator")
    assert "context" in str(excinfo.value)


def test_unknown_prompt_version_raises():
    with pytest.raises(FileNotFoundError):
        render("validator", "v99", context="x")


@pytest.mark.parametrize("name", ["archaeologist", "repairer", "validator", "behavior"])
def test_every_prompt_declares_output_contract(name):
    assert output_contract(name) in {
        "environment-genome",
        "patch-proposal",
        "validation",
        "behavior-plan",
    }


def test_required_vars_are_declared():
    assert set(required_vars("repairer")) == {
        "error_fact",
        "manifest",
        "prior_attempts",
        "memory_cases",
    }


def test_message_hash_is_deterministic():
    first = render("validator", context="x")
    second = render("validator", context="x")
    assert message_hash(first) == message_hash(second)
    assert message_hash(first) != message_hash(render("validator", context="y"))


def test_golden_prompt_hashes_are_stable():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for key, (name, variables) in GOLDEN_RENDERS.items():
        digest = message_hash(render(name, **variables))
        assert digest == golden[key], f"prompt {key} drifted"


def test_list_prompts_contains_required_names():
    assert {"archaeologist", "repairer", "validator", "behavior"} <= set(list_prompts())
