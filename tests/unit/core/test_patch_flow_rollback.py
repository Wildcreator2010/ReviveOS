"""Patch execution must restore the workspace when rerun raises or times out."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from revive_core.sandbox.executor import PatchResult, SandboxHandle
from revive_core.sandbox.patch_flow import PatchProposal, apply_and_verify
from revive_core.sandbox.port_impl import DockerExecutionPort

DIFF = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"


class FakePort:
    def __init__(self) -> None:
        self.restored = False

    async def snapshot_ws(self) -> str:
        return "snapshot"

    async def apply_patch(self, diff: str) -> PatchResult:
        return PatchResult(ok=True, applied_files=["app.py"])

    async def restore_ws(self, token: str) -> None:
        self.restored = True


async def test_rerun_exception_still_restores_the_snapshot() -> None:
    port = FakePort()
    handle = SandboxHandle(container_id="c", ws_path="/workspace", digest=None, job_id="j", backend="fake")
    handle.bind_port(port)

    async def exploding_rerun() -> None:
        raise RuntimeError("backend crashed")

    with pytest.raises(RuntimeError, match="backend crashed"):
        await apply_and_verify(handle, PatchProposal(diff=DIFF), exploding_rerun)

    assert port.restored is True


class FakeContainer:
    def __init__(self) -> None:
        self.argv: list[str] = []
        self.killed = False

    def exec_run(self, argv, **kwargs):
        self.argv = list(argv)
        return SimpleNamespace(exit_code=124, output=(b"", b"timeout"))

    def kill(self) -> None:
        self.killed = True


async def test_timeout_wrapper_keeps_the_container_alive_for_rollback(tmp_path) -> None:
    container = FakeContainer()
    port = DockerExecutionPort(workspace=tmp_path, artifacts_dir=tmp_path / "artifacts", client=object())
    port._container = container

    result = await port.run("pytest", ["python", "-m", "pytest"], timeout=7)

    assert container.argv[:3] == ["timeout", "--kill-after=5", "7s"]
    assert container.killed is False
    assert result.timed_out is True
    assert result.exit_code == -1
