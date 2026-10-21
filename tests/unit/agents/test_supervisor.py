"""T-AG-06: supervisor scripts - success, repair budget, LLM budget."""

from __future__ import annotations

from datetime import datetime

import pytest
from revive_agents.graph import EVENT_TYPES, GraphState, build_graph
from revive_agents.llm import BudgetExceeded
from revive_agents.nodes import GiveUp, Refused
from revive_agents.ports import ExecutionCancelled
from revive_core import schemas
from revive_core.sandbox.executor import RunResult

HIGH_CONFIDENCE = {
    "python": {"version": "3.11", "confidence": 0.95, "evidence": []},
    "os": {"image": "python:3.11", "confidence": 0.9, "evidence": []},
    "dependencies": [],
    "cuda": {"confidence": 0.9, "evidence": []},
    "system_libs": [],
    "overall_confidence": 0.92,
}

LOW_CONFIDENCE = {
    "python": {"version": "2.7", "confidence": 0.3, "evidence": []},
    "os": {"confidence": 0.5, "evidence": []},
    "dependencies": [],
    "cuda": {"confidence": 0.5, "evidence": []},
    "system_libs": [],
    "overall_confidence": 0.4,
}


class FakeExecution:
    def __init__(self, *, build_ok: bool = True) -> None:
        self.build_ok = build_ok
        self.calls: list[tuple] = []

    async def ensure_env(self, genome):
        self.calls.append(("ensure_env", genome))
        return {"handle": "sbx-1"}

    async def run(self, kind: str, argv, timeout):
        self.calls.append((kind, list(argv)))
        if kind == "build":
            return {"ok": self.build_ok, "reason": None if self.build_ok else "R05"}
        if kind == "test":
            return {"ok": True, "passed": 3}
        if kind == "behavior":
            return {"ok": True, "fingerprints": {"stdout": "abc"}}
        return {"ok": True}

    async def apply_patch(self, diff):
        self.calls.append(("apply_patch", diff))
        return {"ok": True}

    async def snapshot_ws(self):
        return "token"

    async def restore_ws(self, token):
        return None


class EventCollector:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, event: dict) -> None:
        self.events.append(event)

    @property
    def types(self) -> list[str]:
        return [event["type"] for event in self.events]


class Outcome:
    def __init__(self, genome, warnings=None) -> None:
        self.genome = genome
        self.warnings = warnings or []


async def test_success_script_event_order_matches_contract():
    collector = EventCollector()

    raised = {**HIGH_CONFIDENCE, "overall_confidence": 0.9}

    async def archaeologist(genome, low, corpus, provider):
        return Outcome(raised)

    async def behavior(handle, plan):
        return {
            "fingerprint": {"plan_ref": "behavior-plan.json", "captured_at": "2026-01-01T00:00:00Z", "cases": []},
            "compatibility": 1.0,
            "matched": True,
            "cases": 1,
        }

    deps = {
        "execution": FakeExecution(build_ok=True),
        "events": collector,
        "archaeologist": archaeologist,
        "behavior": behavior,
    }
    state = GraphState(
        job_id="job-success",
        project={"id": "p1", "build_argv": ["build-it"]},
        genome=LOW_CONFIDENCE,
        behavior_plan={"cases": [{"id": "smoke", "argv": ["true"]}]},
    )
    result = await build_graph(deps).ainvoke(state)

    assert collector.types == [
        "job.queued",
        "archaeology.started",
        "archaeology.evidence",
        "env.inferred",
        "sandbox.created",
        "build.attempt",
        "test.attempt",
        "behavior.captured",
        "behavior.compared",
        "score.computed",
        "capsule.created",
        "job.succeeded",
    ]
    assert result.status == "succeeded"
    assert result.capsule_ref == "capsule://job-success"
    assert set(collector.types) <= set(EVENT_TYPES)


async def test_failure_script_stops_after_five_attempts():
    collector = EventCollector()

    async def repair(error_fact, manifest, prior_attempts, provider):
        return Refused("scripted refusal")

    deps = {
        "execution": FakeExecution(build_ok=False),
        "events": collector,
        "repair": repair,
    }
    state = GraphState(
        job_id="job-fail",
        project={"id": "p2", "build_argv": ["build-it"]},
        genome=HIGH_CONFIDENCE,
    )
    result = await build_graph(deps).ainvoke(state)
    types = collector.types

    assert types.count("build.attempt") == 5
    assert types.count("build.failed") == 5
    assert types.count("repair.attempt") == 4
    assert types[-1] == "job.failed"
    assert collector.events[-1]["payload"]["reason"] == "repair_budget_exhausted"
    assert result.failure_reason == "repair_budget_exhausted"
    assert result.build_attempts == 5


async def test_give_up_terminates_the_branch():
    collector = EventCollector()
    seen: list[tuple] = []

    async def repair(error_fact, manifest, prior_attempts, provider):
        seen.append((error_fact, manifest, prior_attempts, provider))
        return GiveUp("two consecutive failures with the same signature")

    deps = {
        "execution": FakeExecution(build_ok=False),
        "events": collector,
        "repair": repair,
    }
    state = GraphState(
        job_id="job-giveup",
        project={
            "id": "p7",
            "workspace_manifest": {"a.py": {"content": "x = 1\n"}},
        },
        genome=HIGH_CONFIDENCE,
    )
    result = await build_graph(deps).ainvoke(state)

    assert result.failure_reason == "repair_give_up"
    assert collector.types.count("build.attempt") == 1
    assert collector.types[-1] == "job.failed"
    assert collector.events[-1]["payload"]["reason"] == "repair_give_up"
    assert seen and seen[0][2] == []


async def test_budget_exhaustion_fails_job_with_budget_reason():
    collector = EventCollector()

    async def archaeologist(genome, low, corpus, provider):
        raise BudgetExceeded("job budget exhausted")

    deps = {
        "execution": FakeExecution(),
        "events": collector,
        "archaeologist": archaeologist,
    }
    state = GraphState(job_id="job-budget", project={"id": "p3"}, genome=LOW_CONFIDENCE)
    result = await build_graph(deps).ainvoke(state)

    assert collector.types[-1] == "job.failed"
    assert collector.events[-1]["payload"]["reason"] == "budget"
    assert result.failure_reason == "budget"


async def test_event_budget_guard_fails_job():
    collector = EventCollector()
    deps = {
        "execution": FakeExecution(),
        "events": collector,
        "genome": HIGH_CONFIDENCE,
        "max_events": 3,
    }
    state = GraphState(job_id="job-events", project={"id": "p4"}, genome=HIGH_CONFIDENCE)
    result = await build_graph(deps).ainvoke(state)

    assert collector.types[:3] == ["job.queued", "archaeology.started", "env.inferred"]
    assert collector.types[-1] == "job.failed"
    assert collector.events[-1]["payload"]["reason"] == "event_budget_exhausted"
    assert result.failure_reason == "event_budget_exhausted"


async def test_wall_clock_timeout_fails_job():
    collector = EventCollector()
    ticks = {"value": 0.0}

    def clock() -> float:
        ticks["value"] += 1.0
        return ticks["value"]

    deps = {
        "execution": FakeExecution(),
        "events": collector,
        "timeout": 0.5,
        "clock": clock,
    }
    state = GraphState(job_id="job-time", project={"id": "p5"}, genome=HIGH_CONFIDENCE)
    result = await build_graph(deps).ainvoke(state)

    assert collector.types[-1] == "job.failed"
    assert collector.events[-1]["payload"]["reason"] == "timeout"
    assert result.failure_reason == "timeout"


async def test_unexpected_node_error_fails_job_with_safe_reason():
    collector = EventCollector()

    async def archaeologist(genome, low, corpus, provider):
        raise RuntimeError("private provider detail")

    deps = {
        "execution": FakeExecution(),
        "events": collector,
        "archaeologist": archaeologist,
    }
    state = GraphState(job_id="job-internal-error", project={"id": "p8"}, genome=LOW_CONFIDENCE)
    result = await build_graph(deps).ainvoke(state)

    assert result.status == "failed"
    assert result.failure_reason == "internal_error"
    assert collector.types[-1] == "job.failed"
    assert collector.events[-1]["payload"] == {"reason": "internal_error"}


async def test_every_event_matches_the_job_event_contract():
    collector = EventCollector()
    deps = {"execution": FakeExecution(), "events": collector}
    await build_graph(deps).ainvoke(GraphState(job_id="job-events-2", project={"id": "p6"}, genome=HIGH_CONFIDENCE))
    for event in collector.events:
        assert set(event) == {"id", "job_id", "project_id", "ts", "type", "payload"}
        assert event["type"] in EVENT_TYPES
        datetime.fromisoformat(event["ts"])
        schemas.validate(event, "job-event")


async def test_run_result_with_nonzero_exit_code_is_a_failed_build():
    """Regression: a dataclass RunResult used to be coerced to {'value': ...} and
    therefore always reported success, even for exit_code=1."""

    class RunResultExecution(FakeExecution):
        async def run(self, kind, argv, timeout):
            if kind == "build":
                return RunResult(kind="build", argv=list(argv), exit_code=1, backend="test")
            return {"ok": True}

    collector = EventCollector()
    deps = {"execution": RunResultExecution(), "events": collector, "repair": _refuse}
    state = GraphState(job_id="job-runresult", project={"id": "p9"}, genome=HIGH_CONFIDENCE)
    result = await build_graph(deps).ainvoke(state)

    assert result.status == "failed"
    assert result.failure_reason == "repair_budget_exhausted"
    assert collector.types.count("build.failed") == 5
    assert "job.succeeded" not in collector.types


async def _refuse(error_fact, manifest, prior_attempts, provider):
    return Refused("scripted refusal")


async def test_failed_build_rolls_back_the_patch_before_the_next_attempt():
    class RollbackExecution(FakeExecution):
        def __init__(self) -> None:
            super().__init__(build_ok=False)
            self.snapshots: list[str] = []
            self.restored: list[str] = []

        async def snapshot_ws(self):
            token = f"snap-{len(self.snapshots) + 1}"
            self.snapshots.append(token)
            return token

        async def restore_ws(self, token):
            self.restored.append(token)

        async def apply_patch(self, diff):
            self.calls.append(("apply_patch", diff))
            return {"ok": True}

    async def repair(error_fact, manifest, prior_attempts, provider):
        return {"diff": "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-1\n+2\n", "touched_files": ["x.py"]}

    execution = RollbackExecution()
    deps = {"execution": execution, "events": EventCollector(), "repair": repair}
    state = GraphState(
        job_id="job-rollback",
        project={"id": "p10", "workspace_manifest": {"x.py": {"content": "1\n"}}},
        genome=HIGH_CONFIDENCE,
    )
    result = await build_graph(deps).ainvoke(state)

    assert result.status == "failed"
    assert execution.snapshots == ["snap-1", "snap-2", "snap-3", "snap-4"]
    assert execution.restored == execution.snapshots


async def test_caller_cancellation_propagates_instead_of_becoming_internal_error():
    class CancellingExecution(FakeExecution):
        async def ensure_env(self, genome):
            raise ExecutionCancelled("user_cancelled")

    collector = EventCollector()
    deps = {"execution": CancellingExecution(), "events": collector}
    state = GraphState(job_id="job-cancel", project={"id": "p11"}, genome=HIGH_CONFIDENCE)

    with pytest.raises(ExecutionCancelled):
        await build_graph(deps).ainvoke(state)
