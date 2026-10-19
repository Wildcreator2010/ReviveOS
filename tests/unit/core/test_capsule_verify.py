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


def _patch_structural_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify_module,
        "verify_capsule_structure",
        lambda capsule: {"manifest_ok": True, "digests_ok": True, "errors": [], "missing": [], "bad_entries": []},
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
