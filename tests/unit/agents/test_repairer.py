"""T-AG-04: repair permission ceiling, ast.parse, git apply --check, GiveUp."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from revive_agents.limits import MAX_FILES, MAX_ITERATIONS, MAX_LINES
from revive_agents.llm import FakeProvider
from revive_agents.nodes import GitUnavailable, GiveUp, PatchProposal, Refused, repair
from revive_agents.nodes.repairer import find_git

GIT = find_git()
requires_git = pytest.mark.skipif(
    GIT is None,
    reason="git executable not found; set REVIVE_GIT_BIN or install git to run this check",
)

PY_SOURCE = "import collections\n\nis_mapping = isinstance({}, collections.Mapping)\n"

GOOD_DIFF = (
    "diff --git a/legacy_module.py b/legacy_module.py\n"
    "--- a/legacy_module.py\n"
    "+++ b/legacy_module.py\n"
    "@@ -1,3 +1,3 @@\n"
    " import collections\n"
    " \n"
    "-is_mapping = isinstance({}, collections.Mapping)\n"
    "+is_mapping = isinstance({}, collections.abc.Mapping)\n"
)

MANIFEST = {"legacy_module.py": {"sha256": "deadbeef", "lines": 3, "content": PY_SOURCE}}


def provider_for(diff: str, touched_files, *, risk: str = "low", **extra) -> FakeProvider:
    payload = {
        "diff": diff,
        "rationale": "compatibility shim",
        "touched_files": touched_files,
        "lines_added": extra.pop("lines_added", 1),
        "lines_removed": extra.pop("lines_removed", 1),
        "risk": risk,
        **extra,
    }
    return FakeProvider(responder=lambda messages: payload)


def test_permission_ceiling_constants_are_frozen():
    assert (MAX_ITERATIONS, MAX_FILES, MAX_LINES) == (5, 10, 300)


def test_git_resolution_finds_portable_bundle():
    assert GIT is None or Path(GIT).name.lower().startswith("git")


def test_revive_git_bin_env_is_honored(monkeypatch):
    if GIT is None:
        pytest.skip("git executable not available; set REVIVE_GIT_BIN")
    monkeypatch.setenv("REVIVE_GIT_BIN", GIT)
    assert find_git() == GIT


@requires_git
async def test_golden_collections_mapping_patch_passes():
    # A self-managed workspace rather than pytest's tmp_path: the DSH sandbox
    # cannot remove pytest's basetemp, which surfaces as a spurious teardown error.
    workspace = Path(__file__).parent / "_git_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "legacy_module.py").write_text(PY_SOURCE, encoding="utf-8")
    try:
        provider = provider_for(GOOD_DIFF, ["legacy_module.py"])
        result = await repair(
            {"signature": "R05:collections-mapping"},
            MANIFEST,
            [],
            provider,
            workspace=workspace,
        )
        assert isinstance(result, PatchProposal), result
        assert result.touched_files == ["legacy_module.py"]
        assert result.lines_added == 1
        assert result.lines_removed == 1
        assert result.risk == "low"
    finally:
        target = workspace / "legacy_module.py"
        try:
            target.unlink()
        except OSError:
            pass
        try:
            workspace.rmdir()
        except OSError:
            pass


async def test_patch_over_300_lines_is_refused():
    added = "".join(f"+line {index}\n" for index in range(MAX_LINES + 1))
    diff = f"diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n@@ -0,0 +1,{MAX_LINES + 1} @@\n{added}"
    provider = provider_for(diff, ["big.py"])
    result = await repair({"signature": "R01:too-big"}, {"big.py": {"content": ""}}, [], provider, check_git=False)
    assert isinstance(result, Refused)
    assert str(MAX_LINES) in result.reason


async def test_patch_touching_too_many_files_is_refused():
    diff_parts = []
    touched = []
    for index in range(MAX_FILES + 1):
        name = f"mod_{index}.py"
        touched.append(name)
        diff_parts.append(f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-x = 1\n+x = 2\n")
    manifest = {name: {"content": "x = 1\n"} for name in touched}
    provider = provider_for("".join(diff_parts), touched)
    result = await repair({"signature": "R01:many"}, manifest, [], provider, check_git=False)
    assert isinstance(result, Refused)
    assert str(MAX_FILES) in result.reason


async def test_python_syntax_error_is_refused():
    broken_diff = (
        "diff --git a/legacy_module.py b/legacy_module.py\n"
        "--- a/legacy_module.py\n"
        "+++ b/legacy_module.py\n"
        "@@ -1,3 +1,3 @@\n"
        " import collections\n"
        " \n"
        "-is_mapping = isinstance({}, collections.Mapping)\n"
        "+def broken(:\n"
    )
    provider = provider_for(broken_diff, ["legacy_module.py"])
    result = await repair({"signature": "R01:syntax"}, MANIFEST, [], provider, check_git=False)
    assert isinstance(result, Refused)
    assert "syntax error" in result.reason


async def test_file_outside_manifest_is_refused():
    diff = "diff --git a/other.py b/other.py\n--- a/other.py\n+++ b/other.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    provider = provider_for(diff, ["other.py"])
    result = await repair({"signature": "R01:escape"}, MANIFEST, [], provider, check_git=False)
    assert isinstance(result, Refused)
    assert "outside the workspace manifest" in result.reason


async def test_dependency_pin_change_is_refused():
    manifest = {"requirements.txt": {"content": "requests==2.5.0\n"}}
    diff = (
        "diff --git a/requirements.txt b/requirements.txt\n"
        "--- a/requirements.txt\n"
        "+++ b/requirements.txt\n"
        "@@ -1 +1 @@\n"
        "-requests==2.5.0\n"
        "+requests==2.31.0\n"
    )
    provider = provider_for(diff, ["requirements.txt"])
    result = await repair({"signature": "R01:pins"}, manifest, [], provider, check_git=False)
    assert isinstance(result, Refused)
    assert "dependency version" in result.reason


async def test_touched_files_must_match_diff():
    provider = provider_for(GOOD_DIFF, ["somewhere_else.py"])
    result = await repair({"signature": "R01:mismatch"}, MANIFEST, [], provider, check_git=False)
    assert isinstance(result, Refused)
    assert "disagrees" in result.reason


async def test_line_counts_are_recomputed_from_the_diff():
    provider = provider_for(GOOD_DIFF, ["legacy_module.py"], lines_added=9999, lines_removed=9999)
    result = await repair({"signature": "R01:counts"}, MANIFEST, [], provider, check_git=False)
    assert isinstance(result, PatchProposal)
    assert (result.lines_added, result.lines_removed) == (1, 1)


async def test_invalid_unified_diff_is_refused():
    provider = provider_for("this is not a diff at all", ["legacy_module.py"])
    result = await repair({"signature": "R01:garbage"}, MANIFEST, [], provider, check_git=False)
    assert isinstance(result, Refused)
    assert "invalid unified diff" in result.reason


async def test_git_apply_check_failure_is_refused(tmp_path):
    provider = provider_for(GOOD_DIFF, ["legacy_module.py"])
    (tmp_path / "legacy_module.py").write_text(PY_SOURCE, encoding="utf-8")

    def reject(*args, **kwargs):
        return SimpleNamespace(returncode=1, stderr="patch rejected", stdout="")

    result = await repair(
        {"signature": "R01:rejected"},
        MANIFEST,
        [],
        provider,
        workspace=tmp_path,
        git_bin="git",
        runner=reject,
    )

    assert isinstance(result, Refused)
    assert "git apply --check failed: patch rejected" in result.reason


async def test_two_consecutive_same_signature_failures_give_up():
    provider = FakeProvider()
    attempts = [
        {"signature": "R05:collections-mapping", "accepted": False},
        {"signature": "R05:collections-mapping", "accepted": False},
    ]
    result = await repair({"signature": "R05:collections-mapping"}, MANIFEST, attempts, provider)
    assert isinstance(result, GiveUp)
    assert provider.calls == []


async def test_iteration_budget_exhaustion_gives_up():
    provider = FakeProvider()
    attempts = [{"signature": "R05:x", "accepted": False} for _ in range(MAX_ITERATIONS)]
    result = await repair({"signature": "R05:x"}, MANIFEST, attempts, provider)
    assert isinstance(result, GiveUp)
    assert str(MAX_ITERATIONS) in result.reason


async def test_missing_git_raises_clear_error(monkeypatch):
    from revive_core import gitutil as core_git

    def unavailable() -> str:
        raise core_git.GitUnavailableError(
            "git executable not found: set REVIVE_GIT_BIN to the git binary or add git to PATH"
        )

    monkeypatch.setattr(core_git, "find_git", unavailable)
    provider = provider_for(GOOD_DIFF, ["legacy_module.py"])
    with pytest.raises(GitUnavailable) as excinfo:
        await repair({"signature": "R05:git"}, MANIFEST, [], provider)
    assert "REVIVE_GIT_BIN" in str(excinfo.value)
