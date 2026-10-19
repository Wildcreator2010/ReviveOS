"""Behaviour fingerprint capture (T-SB-06).

A fingerprint stores ONLY hashes, bounded excerpt hashes and numeric series.
Raw stdout/stderr never enters it, so user data cannot leak through the
artifact.  The baseline-source priority required by the work order is
implemented in select_baseline():

  1. expected output files that ship with the repository
  2. the original tag replayed in the historic image (run the ORIGINAL first)
  3. values declared by README/paper, entered by a human

The chosen source is always recorded in provenance; when no baseline can be
established the caller gets compatibility=null (never a fabricated 1.0).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from .. import schemas
from ..sandbox.executor import EventPort, RunResult, SandboxHandle
from ..sandbox.runner import read_ref_text

FORMAT = "revive/behavior-fingerprint/v1"
EXCERPT_LIMIT = 2000

ToleranceMode = Literal["exact", "numeric", "structural"]

BASELINE_PRIORITY: dict[str, tuple[int, str]] = {
    "repo_expected_outputs": (1, "expected output files bundled with the repository"),
    "original_tag_replay": (2, "original tag replayed inside the historic image"),
    "declared_values": (3, "values declared by README/paper, entered by a human"),
}


@dataclass(frozen=True)
class Tolerances:
    mode: ToleranceMode = "exact"
    eps_abs: float = 0.0
    eps_rel: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "eps_abs": self.eps_abs, "eps_rel": self.eps_rel}

    @classmethod
    def from_mapping(cls, value: Any) -> Tolerances:
        if value is None:
            return cls()
        if isinstance(value, Tolerances):
            return value
        if isinstance(value, str):
            return cls(mode=value)  # type: ignore[arg-type]
        return cls(
            mode=str(value.get("mode", "exact")),  # type: ignore[arg-type]
            eps_abs=float(value.get("eps_abs", 0.0) or 0.0),
            eps_rel=float(value.get("eps_rel", 0.0) or 0.0),
        )


@dataclass
class CaseSpec:
    id: str
    argv: list[str] = field(default_factory=list)
    tolerance: Tolerances = field(default_factory=Tolerances)
    expect_files: list[str] = field(default_factory=list)
    capture_structural: bool = False
    capture_numeric: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CaseSpec:
        return cls(
            id=str(value.get("id", "")),
            argv=[str(item) for item in value.get("argv", []) or []],
            tolerance=Tolerances.from_mapping(value.get("tolerance")),
            expect_files=[str(item) for item in value.get("expect_files", []) or []],
            capture_structural=bool(value.get("capture_structural", False)),
            capture_numeric=bool(value.get("capture_numeric", False)),
        )


@dataclass
class BehaviorPlan:
    cases: list[CaseSpec]
    plan_ref: str = "behavior-plan.json"
    timeout_per_case: float = 60.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, plan_ref: str | None = None) -> BehaviorPlan:
        raw_cases = value.get("cases", []) or []
        cases = [CaseSpec.from_mapping(item) for item in raw_cases if isinstance(item, Mapping)]
        budget = value.get("budget", {}) or {}
        timeout = float(budget.get("timeout_per_case", 60.0) or 60.0)
        return cls(
            cases=cases,
            plan_ref=plan_ref or str(value.get("plan_ref", "behavior-plan.json")),
            timeout_per_case=timeout,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_ref": self.plan_ref,
            "cases": [
                {
                    "id": case.id,
                    "argv": list(case.argv),
                    "tolerance": case.tolerance.to_dict(),
                    "expect_files": list(case.expect_files),
                    "capture_structural": case.capture_structural,
                    "capture_numeric": case.capture_numeric,
                }
                for case in self.cases
            ],
            "budget": {"max_cases": len(self.cases), "timeout_per_case": self.timeout_per_case},
        }


@dataclass(frozen=True)
class FileDigest:
    glob: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"glob": self.glob, "sha256": self.sha256}


@dataclass(frozen=True)
class NumericSeries:
    name: str
    values: list[float]
    dtype: str = "float"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "values": list(self.values), "dtype": self.dtype}


@dataclass
class CaseFingerprint:
    id: str
    exit_code: int
    stdout_hash: str
    argv: list[str] = field(default_factory=list)
    timed_out: bool = False
    stderr_hash: str | None = None
    stdout_excerpt_hash: str | None = None
    output_files: list[FileDigest] = field(default_factory=list)
    numeric_series: list[NumericSeries] = field(default_factory=list)
    structural: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "stdout_hash": self.stdout_hash,
            "stderr_hash": self.stderr_hash,
            "stdout_excerpt_hash": self.stdout_excerpt_hash,
            "output_files": [item.to_dict() for item in self.output_files],
            "numeric_series": [item.to_dict() for item in self.numeric_series],
            "structural": self.structural,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CaseFingerprint:
        return cls(
            id=str(value.get("id", "")),
            exit_code=int(value.get("exit_code", 0)),
            stdout_hash=str(value.get("stdout_hash", "")),
            argv=[str(item) for item in value.get("argv", []) or []],
            timed_out=bool(value.get("timed_out", False)),
            stderr_hash=value.get("stderr_hash"),
            stdout_excerpt_hash=value.get("stdout_excerpt_hash"),
            output_files=[
                FileDigest(glob=str(item.get("glob", "")), sha256=str(item.get("sha256", "")))
                for item in value.get("output_files", []) or []
            ],
            numeric_series=[
                NumericSeries(
                    name=str(item.get("name", "")),
                    values=[float(number) for number in item.get("values", []) or []],
                    dtype=str(item.get("dtype", "float")),
                )
                for item in value.get("numeric_series", []) or []
            ],
            structural=value.get("structural"),
        )


@dataclass
class Fingerprint:
    plan_ref: str
    captured_at: str
    cases: list[CaseFingerprint]
    baseline_source: dict[str, Any] | None = None
    format: str = FORMAT

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "format": self.format,
            "plan_ref": self.plan_ref,
            "captured_at": self.captured_at,
            "cases": [case.to_dict() for case in self.cases],
        }
        if self.baseline_source is not None:
            payload["baseline_source"] = self.baseline_source
        return payload

    def validate(self) -> None:
        schemas.validate(self.to_dict(), "fingerprint")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Fingerprint:
        return cls(
            plan_ref=str(value.get("plan_ref", "")),
            captured_at=str(value.get("captured_at", "")),
            cases=[CaseFingerprint.from_mapping(item) for item in value.get("cases", []) or []],
            baseline_source=value.get("baseline_source"),
            format=str(value.get("format", FORMAT)),
        )


@dataclass(frozen=True)
class BaselineChoice:
    priority: int | None
    kind: str
    reference: str
    fingerprint: Fingerprint | None = None

    @property
    def present(self) -> bool:
        return self.fingerprint is not None

    def provenance(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "kind": self.kind,
            "reference": self.reference,
            "baseline_present": self.present,
        }


def select_baseline(
    *,
    repo_expected: Fingerprint | None = None,
    original_replay: Fingerprint | None = None,
    declared: Fingerprint | None = None,
    references: Mapping[str, str] | None = None,
) -> BaselineChoice:
    """Apply the mandated baseline-source priority order."""

    refs = dict(references or {})
    for kind, fingerprint in (
        ("repo_expected_outputs", repo_expected),
        ("original_tag_replay", original_replay),
        ("declared_values", declared),
    ):
        if fingerprint is not None:
            priority, description = BASELINE_PRIORITY[kind]
            reference = refs.get(kind) or description
            if fingerprint.baseline_source is None:
                fingerprint = Fingerprint(
                    plan_ref=fingerprint.plan_ref,
                    captured_at=fingerprint.captured_at,
                    cases=fingerprint.cases,
                    baseline_source={"priority": priority, "kind": kind, "reference": reference},
                )
            return BaselineChoice(priority=priority, kind=kind, reference=reference, fingerprint=fingerprint)
    return BaselineChoice(priority=None, kind="none", reference="no baseline available", fingerprint=None)


# --------------------------------------------------------------------------
# Capture helpers
# --------------------------------------------------------------------------
def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def iter_workspace_files(handle: SandboxHandle, root: str = "", *, limit: int = 2000) -> list[str]:
    """Recursively list workspace-relative file paths via the port's list_dir."""

    port = handle.port
    lister = getattr(port, "list_dir", None)
    if lister is None:
        return []
    found: list[str] = []
    stack: list[tuple[str, int]] = [(root, 0)]
    while stack and len(found) < limit:
        current, depth = stack.pop()
        if depth > 12:
            continue
        try:
            entries = lister(current)
        except OSError:
            continue
        prefix = current.strip("/")
        for entry in entries:
            rel = f"{prefix}/{entry}" if prefix else entry
            if entry.startswith(".") or entry in {"__pycache__"}:
                continue
            probe = getattr(port, "read_text", None)
            if probe is not None:
                try:
                    probe(rel)
                    found.append(rel)
                    continue
                except (OSError, FileNotFoundError, ValueError):
                    pass
            stack.append((rel, depth + 1))
    return found


def _match_glob(paths: Iterable[str], pattern: str) -> list[str]:
    import fnmatch

    normalised = pattern.replace("\\", "/")
    return sorted(
        path for path in paths if fnmatch.fnmatch(path, normalised) or fnmatch.fnmatch(path.split("/")[-1], normalised)
    )


def _read(handle: SandboxHandle, rel: str) -> str:
    port = handle.port
    reader = getattr(port, "read_text", None)
    if reader is None:
        return ""
    try:
        return str(reader(rel))
    except (OSError, FileNotFoundError, ValueError):
        return ""


def _numeric_from_json(value: Any, prefix: str = "") -> list[NumericSeries]:
    series: list[NumericSeries] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            series.extend(_numeric_from_json(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        numbers: list[float] = []
        all_numeric = True
        for item in value:
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                numbers.append(float(item))
            else:
                all_numeric = False
                series.extend(_numeric_from_json(item, prefix))
        if all_numeric and numbers:
            dtype = "int" if all(float(number).is_integer() for number in numbers) else "float"
            series.append(NumericSeries(name=prefix or "values", values=numbers, dtype=dtype))
    return series


async def capture(
    handle: SandboxHandle,
    plan: BehaviorPlan | Mapping[str, Any],
    *,
    events: EventPort | None = None,
    clock: Any = None,
    baseline_source: Mapping[str, Any] | None = None,
) -> Fingerprint:
    """Run every behaviour-plan case and hash its observable output."""

    if not isinstance(plan, BehaviorPlan):
        plan = BehaviorPlan.from_mapping(plan)
    port = handle.port
    if port is None:
        raise RuntimeError("handle is not bound to an execution port")
    workspace_files = iter_workspace_files(handle)
    cases: list[CaseFingerprint] = []
    for case in plan.cases:
        result: RunResult = await port.run("behavior", list(case.argv), plan.timeout_per_case)
        stdout_text = read_ref_text(handle, result.stdout_ref, limit=10_000_000)
        stderr_text = read_ref_text(handle, result.stderr_ref, limit=10_000_000)
        output_files: list[FileDigest] = []
        for pattern in case.expect_files:
            for matched in _match_glob(workspace_files, pattern):
                output_files.append(FileDigest(glob=pattern, sha256=_sha256_text(_read(handle, matched))))
        numeric: list[NumericSeries] = []
        structural: Any = None
        if case.capture_structural or case.capture_numeric:
            try:
                parsed = json.loads(stdout_text)
            except (ValueError, TypeError):
                parsed = None
            if parsed is not None:
                structural = parsed if case.capture_structural else None
                if case.capture_numeric:
                    numeric = _numeric_from_json(parsed)
        cases.append(
            CaseFingerprint(
                id=case.id,
                exit_code=result.exit_code,
                stdout_hash=_sha256_text(stdout_text),
                argv=list(case.argv),
                timed_out=result.timed_out,
                stderr_hash=_sha256_text(stderr_text) if stderr_text else None,
                stdout_excerpt_hash=_sha256_text(stdout_text[:EXCERPT_LIMIT]) if stdout_text else None,
                output_files=output_files,
                numeric_series=numeric,
                structural=structural,
            )
        )
    captured_at = datetime.now(UTC).isoformat()
    if clock is not None:  # deterministic tests
        captured_at = clock() if callable(clock) else str(clock)
    fingerprint = Fingerprint(
        plan_ref=plan.plan_ref,
        captured_at=captured_at,
        cases=cases,
        baseline_source=dict(baseline_source) if baseline_source else None,
    )
    fingerprint.validate()
    if events is not None:
        await events.emit(
            {
                "type": "behavior.captured",
                "payload": {"plan_ref": plan.plan_ref, "cases": len(cases)},
            }
        )
    return fingerprint


__all__ = [
    "FORMAT",
    "EXCERPT_LIMIT",
    "BASELINE_PRIORITY",
    "Tolerances",
    "ToleranceMode",
    "CaseSpec",
    "BehaviorPlan",
    "FileDigest",
    "NumericSeries",
    "CaseFingerprint",
    "Fingerprint",
    "BaselineChoice",
    "select_baseline",
    "capture",
    "iter_workspace_files",
]
