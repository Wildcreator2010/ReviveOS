"""Sandbox patch limits come from the diff, not from the proposal's own counters."""

from __future__ import annotations

from revive_core.sandbox.patch_flow import MAX_FILES, MAX_LINES, PatchProposal, validate_proposal


def _one_file(name: str, added: int = 1) -> str:
    body = "".join(f"+line {index}\n" for index in range(added))
    return f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -1 +1,{added + 1} @@\n-original\n{body}"


def test_underreported_line_count_is_refused() -> None:
    proposal = PatchProposal(diff=_one_file("app.py", MAX_LINES + 1), lines_added=0, lines_removed=0)

    refusal = validate_proposal(proposal)

    assert refusal is not None and "lines" in refusal


def test_underreported_file_count_is_refused() -> None:
    diff = "".join(_one_file(f"module_{index}.py") for index in range(MAX_FILES + 1))
    proposal = PatchProposal(diff=diff, touched_files=[], lines_added=0, lines_removed=0)

    refusal = validate_proposal(proposal)

    assert refusal is not None and "files" in refusal


def test_small_diff_stays_valid() -> None:
    assert validate_proposal(PatchProposal(diff=_one_file("app.py"))) is None


def test_patch_cannot_modify_tests_or_their_configuration() -> None:
    for name in ("tests/test_app.py", "legacy_test.py", "conftest.py", "pytest.ini"):
        refusal = validate_proposal(PatchProposal(diff=_one_file(name)))
        assert refusal is not None and "test" in refusal.lower()
