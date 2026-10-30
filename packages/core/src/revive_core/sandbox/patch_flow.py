"""Repair loop: apply a PatchProposal with snapshot/rollback (T-SB-05).

Order is fixed and non-negotiable:

    validate -> snapshot -> apply -> rerun -> (keep | rollback)

A diff is never trusted: the caller MUST pass a rerun callable.  A patch that
applies cleanly but does not turn the stage green is rolled back to the exact
pre-patch workspace.  Applying the same patch twice is refused via a content
token, so a retry loop cannot silently stack duplicates.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .diffapply import DiffApplyError, parse_diff
from .executor import EventPort, PatchResult, SandboxHandle, SnapshotToken

# Hard permission ceiling (global red line #7).  Kept in sync with
# revive_agents.limits by tests/unit/sandbox/test_patch_flow_limits.py.
MAX_ITERATIONS = 5
MAX_FILES = 10
MAX_LINES = 300

_TEST_PATH = re.compile(
    r"(^|/)(tests?)(/|$)|(^|/)test_[^/]*\.py$|(^|/)[^/]*_test\.py$|(^|/)conftest\.py$|(^|/)(pytest|tox)\.ini$|(^|/)noxfile\.py$",
    re.IGNORECASE,
)


def protected_patch_reason(path: str) -> str | None:
    normalized = path.replace("\\", "/").lstrip("./").lower()
    if _TEST_PATH.search(normalized):
        return f"test files are immutable under the repair policy: {path}"
    return None


@dataclass
class PatchProposal:
    """The subset of T-AG-04 PatchProposal the sandbox needs."""

    diff: str
    touched_files: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    rationale: str = ""

    @classmethod
    def coerce(cls, value: Any) -> PatchProposal:
        if isinstance(value, PatchProposal):
            return value
        if isinstance(value, Mapping):
            return cls(
                diff=str(value.get("diff", "")),
                touched_files=[str(item) for item in value.get("touched_files", []) or []],
                lines_added=int(value.get("lines_added", 0) or 0),
                lines_removed=int(value.get("lines_removed", 0) or 0),
                rationale=str(value.get("rationale", "") or ""),
            )
        return cls(
            diff=str(getattr(value, "diff", "")),
            touched_files=[str(item) for item in getattr(value, "touched_files", []) or []],
            lines_added=int(getattr(value, "lines_added", 0) or 0),
            lines_removed=int(getattr(value, "lines_removed", 0) or 0),
            rationale=str(getattr(value, "rationale", "") or ""),
        )

    @property
    def token(self) -> str:
        return hashlib.sha256(self.diff.encode("utf-8")).hexdigest()[:16]


@dataclass
class PatchOutcome:
    applied: bool
    snapshot_token: SnapshotToken | None = None
    rerun_result: Any = None
    rolled_back: bool = False
    patch_id: str = ""
    reason: str = ""
    validation: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "snapshot_token": self.snapshot_token.to_dict() if self.snapshot_token else None,
            "rolled_back": self.rolled_back,
            "patch_id": self.patch_id,
            "reason": self.reason,
            "validation": self.validation,
            "rerun_ok": _run_ok(self.rerun_result) if self.rerun_result is not None else None,
        }


class PatchRecorder:
    """In-memory patches/patch-<seq>.diff list (the capsule builder persists it)."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def add(self, diff: str) -> str:
        name = f"patch-{len(self.entries) + 1:03d}.diff"
        self.entries.append((name, diff))
        return name

    def write_to(self, root: str | Path) -> list[Path]:
        directory = Path(root)
        directory.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for name, diff in self.entries:
            path = directory / name
            path.write_text(diff if diff.endswith("\n") else diff + "\n", encoding="utf-8")
            written.append(path)
        return written

    def __len__(self) -> int:
        return len(self.entries)


def validate_proposal(proposal: PatchProposal) -> str | None:
    """Return a refusal reason, or None when the proposal is acceptable."""

    if not proposal.diff.strip():
        return "empty diff"
    if not (proposal.diff.lstrip().startswith("diff --git") or proposal.diff.lstrip().startswith("--- ")):
        return "not a unified diff"
    try:
        patches = parse_diff(proposal.diff)
    except DiffApplyError as exc:
        return f"invalid unified diff: {exc}"
    # Never trust the proposal's self-reported counters: derive them from the diff.
    files = {patch.path for patch in patches if patch.path}
    lines = sum(1 for patch in patches for hunk in patch.hunks for tag, _text in hunk.lines if tag in {"+", "-"})
    if len(files) > MAX_FILES:
        return f"patch touches {len(files)} files (limit {MAX_FILES})"
    if lines > MAX_LINES:
        return f"patch changes {lines} lines (limit {MAX_LINES})"
    for path in sorted(files):
        reason = protected_patch_reason(path)
        if reason is not None:
            return reason
    return None


def _run_ok(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    ok = getattr(value, "ok", None)
    if ok is not None:
        return bool(ok)
    if isinstance(value, Mapping):
        return bool(value.get("ok", False))
    return bool(value)


async def _call(func: Callable[[], Any]) -> Any:
    result = func()
    if inspect.isawaitable(result):
        return await result
    return result


async def apply_and_verify(
    handle: SandboxHandle,
    proposal: Any,
    rerun: Callable[[], Any],
    *,
    events: EventPort | None = None,
    recorder: PatchRecorder | None = None,
    applied_tokens: set[str] | None = None,
) -> PatchOutcome:
    """Apply a patch, rerun the stage, roll back on failure."""

    port = handle.port
    if port is None:
        raise RuntimeError("handle is not bound to an execution port")
    candidate = PatchProposal.coerce(proposal)
    refusal = validate_proposal(candidate)
    if refusal is not None:
        return PatchOutcome(applied=False, patch_id=candidate.token, reason=refusal, validation=refusal)

    tokens = applied_tokens if applied_tokens is not None else set()
    if candidate.token in tokens:
        return PatchOutcome(
            applied=False,
            patch_id=candidate.token,
            reason="patch already applied (idempotency token matches)",
            validation="duplicate",
        )

    snapshot: SnapshotToken | None = await port.snapshot_ws()
    applied: PatchResult = await port.apply_patch(candidate.diff)
    if not applied.ok:
        if snapshot is not None:
            await port.restore_ws(snapshot)
        if events is not None:
            await events.emit({"type": "repair.attempt", "payload": {"applied": False, "reason": applied.reason}})
        return PatchOutcome(
            applied=False,
            snapshot_token=snapshot,
            rolled_back=True,
            patch_id=candidate.token,
            reason=applied.reason or "apply failed",
            validation="apply_failed",
        )

    try:
        rerun_result = await _call(rerun)
    except Exception:
        if snapshot is not None:
            await port.restore_ws(snapshot)
        if events is not None:
            await events.emit({"type": "repair.attempt", "payload": {"applied": True, "rolled_back": True}})
        raise
    if not _run_ok(rerun_result):
        await port.restore_ws(snapshot)
        if events is not None:
            await events.emit({"type": "repair.attempt", "payload": {"applied": True, "rolled_back": True}})
        return PatchOutcome(
            applied=True,
            snapshot_token=snapshot,
            rerun_result=rerun_result,
            rolled_back=True,
            patch_id=candidate.token,
            reason="rerun failed after applying the patch; rolled back",
        )

    tokens.add(candidate.token)
    if recorder is not None:
        recorder.add(candidate.diff)
    if events is not None:
        await events.emit(
            {
                "type": "repair.applied",
                "payload": {
                    "patch_id": candidate.token,
                    "files": list(applied.applied_files) or list(candidate.touched_files),
                },
            }
        )
    return PatchOutcome(
        applied=True,
        snapshot_token=snapshot,
        rerun_result=rerun_result,
        rolled_back=False,
        patch_id=candidate.token,
    )


__all__ = [
    "MAX_ITERATIONS",
    "MAX_FILES",
    "MAX_LINES",
    "PatchProposal",
    "PatchOutcome",
    "PatchRecorder",
    "validate_proposal",
    "apply_and_verify",
]
