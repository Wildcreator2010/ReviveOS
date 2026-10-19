"""T-AG-05: behaviour baseline, existing-test wrapping and network filtering."""

from __future__ import annotations

from revive_agents.llm import FakeProvider
from revive_agents.nodes import behavior_plan
from revive_agents.nodes.behavior_planner import MAX_CASES, BehaviorCase, network_target


def test_network_target_detection():
    assert network_target(["https://evil.example.com/x"]) is not None
    assert network_target(["curl", "http://example.com"]) is not None
    assert network_target(["http://127.0.0.1:8000/health"]) is None
    assert network_target(["--help"]) is None


async def test_plan_wraps_help_and_existing_tests_without_provider():
    plan = await behavior_plan({"entry": "main.py"}, "readme text", tests_dir="tests", provider=None)
    argv_sets = [case["argv"] for case in plan["cases"]]
    assert ["--help"] in argv_sets
    assert any("pytest" in token for argv in argv_sets for token in argv)
    assert set(plan.keys()) == {"cases", "budget"}
    assert plan["budget"]["max_cases"] == MAX_CASES
    for case in plan["cases"]:
        BehaviorCase.model_validate(case)


async def test_llm_cases_are_validated_and_network_cases_dropped():
    payload = {
        "cases": [
            {
                "id": "good",
                "argv": ["--version"],
                "expect_files": ["out.txt"],
                "tolerance": {"mode": "numeric", "eps": 0.01},
            },
            {
                "id": "net",
                "argv": ["fetch", "https://example.com/data.json"],
                "tolerance": {"mode": "exact"},
            },
            {"id": "extra-field", "argv": ["--x"], "bogus": 1},
        ]
    }
    provider = FakeProvider(responder=lambda messages: payload)
    plan = await behavior_plan({"e": 1}, "readme", tests_dir="tests", provider=provider)
    ids = [case["id"] for case in plan["cases"]]
    assert "good" in ids
    assert "net" not in ids
    assert "extra-field" not in ids
    for case in plan["cases"]:
        BehaviorCase.model_validate(case)


async def test_max_cases_is_enforced():
    payload = {"cases": [{"id": f"case-{index}", "argv": ["--x"]} for index in range(50)]}
    provider = FakeProvider(responder=lambda messages: payload)
    plan = await behavior_plan({}, "readme", provider=provider)
    assert len(plan["cases"]) == MAX_CASES
