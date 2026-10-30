from __future__ import annotations

import importlib
from pathlib import Path

import pytest

verify_module = importlib.import_module("revive_core.capsule.verify")


class SuccessfulRebuilder:
    name = "test"

    def __init__(self) -> None:
        self.workdir: Path | None = None

    async def rebuild(self, capsule_dir: Path):
        self.workdir = capsule_dir
        assert (capsule_dir / "manifest.json").is_file()
        return verify_module.RebuildResult(ok=True, behavior_rematch=True)


class FailingRebuilder:
    name = "test"

    def __init__(self) -> None:
        self.workdir: Path | None = None

    async def rebuild(self, capsule_dir: Path):
        self.workdir = capsule_dir
        raise RuntimeError("rebuild failed")


class UnverifiedRebuilder:
    name = "test"

    async def rebuild(self, capsule_dir: Path):
        return verify_module.RebuildResult(ok=True, behavior_rematch=None)


class ScoreMismatchRebuilder:
    name = "test"

    async def rebuild(self, capsule_dir: Path):
        return verify_module.RebuildResult(ok=True, behavior_rematch=True, score_reproduced=70.0)


def _patch_structural_verification(monkeypatch: pytest.MonkeyPatch, manifest: dict | None = None) -> None:
    monkeypatch.setattr(
        verify_module,
        "verify_capsule_structure",
        lambda capsule: {
            "manifest_ok": True,
            "digests_ok": True,
            "errors": [],
            "missing": [],
            "bad_entries": [],
            "manifest": manifest or {},
        },
    )

    def extract(capsule: str | Path, destination: str | Path) -> dict[str, Path]:
        manifest = Path(destination) / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        return {"manifest.json": manifest}

    monkeypatch.setattr(verify_module, "extract_capsule", extract)


@pytest.mark.asyncio
async def test_verify_without_rebuilder_is_not_reported_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_structural_verification(monkeypatch)

    report = await verify_module.verify("capsule.revive")

    assert report.verified is False
    assert report.exit_code == verify_module.EXIT_CORRUPT


@pytest.mark.asyncio
async def test_verify_removes_rebuild_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_structural_verification(monkeypatch)
    monkeypatch.setenv("REVIVE_TMP_DIR", str(tmp_path))
    rebuilder = SuccessfulRebuilder()

    report = await verify_module.verify("capsule.revive", rebuilder=rebuilder)

    assert report.verified is True
    assert rebuilder.workdir is not None
    assert not rebuilder.workdir.exists()


@pytest.mark.asyncio
async def test_verify_removes_rebuild_workspace_after_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_structural_verification(monkeypatch)
    monkeypatch.setenv("REVIVE_TMP_DIR", str(tmp_path))
    rebuilder = FailingRebuilder()

    with pytest.raises(RuntimeError, match="rebuild failed"):
        await verify_module.verify("capsule.revive", rebuilder=rebuilder)

    assert rebuilder.workdir is not None
    assert not rebuilder.workdir.exists()


@pytest.mark.asyncio
async def test_missing_behavior_rematch_is_not_reported_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_structural_verification(monkeypatch)

    report = await verify_module.verify("capsule.revive", rebuilder=UnverifiedRebuilder())

    assert report.verified is False
    assert report.exit_code == verify_module.EXIT_CORRUPT
    assert any("behavior" in error for error in report.errors)


@pytest.mark.asyncio
async def test_score_mismatch_is_reported_as_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_structural_verification(monkeypatch, {"score": {"total": 80.0}})

    report = await verify_module.verify(
        "capsule.revive",
        rebuilder=ScoreMismatchRebuilder(),
        score_recompute=lambda manifest: 70.0,
    )

    assert report.verified is False
    assert report.exit_code == verify_module.EXIT_CORRUPT
    assert report.score_reproduced == 70.0
    assert any("score" in error.lower() for error in report.errors)


@pytest.mark.asyncio
async def test_rebuilder_score_is_compared_without_a_recompute_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_structural_verification(monkeypatch, {"score": {"total": 80.0}})

    report = await verify_module.verify("capsule.revive", rebuilder=ScoreMismatchRebuilder())

    assert report.verified is False
    assert report.exit_code == verify_module.EXIT_CORRUPT
    assert any("score" in error.lower() for error in report.errors)
