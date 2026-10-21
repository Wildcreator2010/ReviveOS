"""The worker must be able to locate the repository it was asked to revive."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from revive_agents.nodes.repairer import workspace_manifest
from revive_api.tasks import pipeline
from revive_core.behavior.capture import BehaviorPlan, CaseSpec
from revive_core.sandbox.executor import ArtifactRef, RunResult, SandboxHandle


@pytest.mark.asyncio
async def test_materialise_source_uses_the_job_repo_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_fetch(url: str, destination: Path) -> SimpleNamespace:
        calls.append((url, destination))
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "README").write_text("ok", encoding="utf-8")
        return SimpleNamespace(path=destination)

    monkeypatch.setattr(pipeline, "fetch_repo", fake_fetch)
    job = SimpleNamespace(id="rev_job_source", metadata={"repo_url": "https://github.com/acme/demo"})

    source = await pipeline._materialise_source(job, tmp_path)

    assert calls == [("https://github.com/acme/demo", tmp_path / "revive-source-rev_job_source")]
    assert source == tmp_path / "revive-source-rev_job_source"


@pytest.mark.asyncio
async def test_materialise_source_refuses_to_clone_an_empty_url(tmp_path: Path) -> None:
    job = SimpleNamespace(id="rev_job_missing", metadata={})

    with pytest.raises(ValueError, match="repo_url"):
        await pipeline._materialise_source(job, tmp_path)


def test_workspace_manifest_contains_only_small_text_files(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("print('hi')\n", encoding="utf-8", newline="\n")
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")

    manifest = workspace_manifest(tmp_path)

    assert set(manifest) == {"pkg/app.py"}
    assert manifest["pkg/app.py"]["lines"] == "print('hi')\n"
    assert len(manifest["pkg/app.py"]["sha256"]) == 64


@pytest.mark.asyncio
async def test_behavior_runner_captures_a_real_exit_code_and_stdout_hash(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "stdout.txt").write_text("ok\n", encoding="utf-8")
    digest = hashlib.sha256(b"ok\n").hexdigest()

    class Port:
        async def run(self, kind: str, argv: list[str], timeout: float) -> RunResult:
            return RunResult(
                kind=kind,
                argv=argv,
                exit_code=0,
                stdout_ref=ArtifactRef("stdout.txt", digest, 3),
                backend="fake",
            )

        def list_dir(self, rel_path: str = "") -> list[str]:
            return []

        def read_text(self, rel_path: str) -> str:
            raise FileNotFoundError(rel_path)

    handle = SandboxHandle(
        container_id="local",
        ws_path=str(tmp_path),
        digest=None,
        job_id="job",
        backend="fake",
        meta={"artifacts_dir": str(artifacts)},
    ).bind_port(Port())
    plan = BehaviorPlan(cases=[CaseSpec(id="smoke", argv=["true"])])

    outcome = await pipeline._behavior_runner(tmp_path)(handle, plan)

    assert outcome["cases"] == 1
    assert outcome["matched"] is False  # no baseline => never fabricate compatibility
    assert outcome["fingerprint"]["cases"][0]["exit_code"] == 0
    assert outcome["fingerprint"]["cases"][0]["stdout_hash"] == digest
