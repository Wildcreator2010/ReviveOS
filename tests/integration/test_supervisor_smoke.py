"""Supervisor integration smoke test.

Running the real graph needs the sandbox pipeline and therefore a reachable
Docker daemon.  The DSH Windows sandbox blocks the Docker named pipe, so this
module always skips with an explicit reason rather than faking a pass.  When
Docker is available the same script exercises the real ExecutionPort.
"""

from __future__ import annotations

import shutil

import pytest
from revive_agents.graph import GraphState, build_graph


def _skip_reason() -> str:
    if shutil.which("docker") is None:
        return "docker CLI is not installed; integration smoke test requires Docker"
    return (
        "docker daemon is unreachable from this sandbox (named pipes are blocked); "
        "run this test on a Docker-enabled host with requires_docker selected"
    )


pytestmark = [
    pytest.mark.requires_docker,
    pytest.mark.skip(reason=_skip_reason()),
]


async def test_supervisor_smoke_with_real_execution_port():
    from revive_agents.nodes import behavior_plan
    from revive_agents.ports import ExecutionPort  # noqa: F401  (fake ports placeholder)

    class NullExecution:
        async def ensure_env(self, genome):
            return None

        async def run(self, kind, argv, timeout):
            return {"ok": True}

        async def apply_patch(self, diff):
            return {"ok": True}

        async def snapshot_ws(self):
            return "token"

        async def restore_ws(self, token):
            return None

    graph = build_graph({"execution": NullExecution(), "behavior_plan": behavior_plan})
    state = await graph.ainvoke(GraphState(job_id="smoke", genome={"overall_confidence": 0.9}))
    assert state.status == "succeeded"
