"""Behaviour equivalence comparison (T-SB-06).

Pure logic: no sandbox, no LLM, no network.  Three tolerance modes:

  exact       - stdout hash and exit code must be identical
  numeric     - element-wise |a-b| <= eps_abs + eps_rel*|b| over numeric series
  structural  - the JSON key tree must have the same shape, leaves compared
                with the numeric tolerance

compare() never fabricates a result: with no baseline it returns
compatibility=None and degraded=True.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .capture import (
    CaseFingerprint,
    Fingerprint,
    ToleranceMode,
    Tolerances,
)


@dataclass
class CaseComparison:
    case_id: str
    ok: bool
    compatibility: float
    drifted_fields: list[str] = field(default_factory=list)
    mode: ToleranceMode = "exact"

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "ok": self.ok,
            "compatibility": self.compatibility,
            "drifted_fields": list(self.drifted_fields),
            "mode": self.mode,
        }


@dataclass
class BehaviorResult:
    compatibility: float | None
    per_case: list[CaseComparison] = field(default_factory=list)
    drifted_fields: list[str] = field(default_factory=list)
    baseline_source: dict[str, Any] | None = None
    degraded: bool = False

    @property
    def ok(self) -> bool:
        return self.compatibility == 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatibility": self.compatibility,
            "ok": self.ok,
            "degraded": self.degraded,
            "baseline_source": self.baseline_source,
            "drifted_fields": list(self.drifted_fields),
            "per_case": [item.to_dict() for item in self.per_case],
        }


def _as_fingerprint(value: Any) -> Fingerprint | None:
    if value is None:
        return None
    if isinstance(value, Fingerprint):
        return value
    if isinstance(value, Mapping):
        return Fingerprint.from_mapping(value)
    return None


def _tolerance_for(tolerances: Tolerances | Mapping[str, Any] | None, case_id: str) -> Tolerances:
    if tolerances is None:
        return Tolerances()
    if isinstance(tolerances, Tolerances):
        return tolerances
    if isinstance(tolerances, str):
        return Tolerances(mode=tolerances)
    entry = tolerances.get(case_id)
    if entry is None:
        entry = tolerances.get("default")
    return Tolerances.from_mapping(entry)


def _file_map(case: CaseFingerprint) -> dict[str, str]:
    return {item.glob: item.sha256 for item in case.output_files}


def _compare_exact(baseline: CaseFingerprint, after: CaseFingerprint) -> tuple[float, list[str]]:
    checks: list[bool] = []
    drifted: list[str] = []

    def check(condition: bool, field_name: str) -> None:
        checks.append(condition)
        if not condition:
            drifted.append(field_name)

    check(baseline.exit_code == after.exit_code, f"{baseline.id}.exit_code")
    check(baseline.timed_out == after.timed_out, f"{baseline.id}.timed_out")
    check(baseline.stdout_hash == after.stdout_hash, f"{baseline.id}.stdout_hash")
    base_files = _file_map(baseline)
    after_files = _file_map(after)
    for pattern, digest in base_files.items():
        check(after_files.get(pattern) == digest, f"{baseline.id}.output_files[{pattern}]")
    for pattern in after_files:
        if pattern not in base_files:
            check(False, f"{baseline.id}.output_files[{pattern}]:unexpected")
    compatibility = sum(1 for item in checks if item) / len(checks) if checks else 1.0
    return compatibility, drifted


def _compare_numeric(
    baseline: CaseFingerprint, after: CaseFingerprint, tolerance: Tolerances
) -> tuple[float, list[str]]:
    drifted: list[str] = []
    total = 0
    matched = 0
    if baseline.exit_code != after.exit_code:
        drifted.append(f"{baseline.id}.exit_code")
        total += 1
    else:
        total += 1
        matched += 1
    after_series = {series.name: series for series in after.numeric_series}
    for series in baseline.numeric_series:
        candidate = after_series.get(series.name)
        if candidate is None:
            drifted.append(f"{baseline.id}.{series.name}:missing")
            total += len(series.values) or 1
            continue
        if len(candidate.values) != len(series.values):
            drifted.append(f"{baseline.id}.{series.name}.length")
            total += max(len(series.values), 1)
            continue
        for index, (left, right) in enumerate(zip(series.values, candidate.values, strict=False)):
            total += 1
            if abs(left - right) <= tolerance.eps_abs + tolerance.eps_rel * abs(right):
                matched += 1
            else:
                drifted.append(f"{baseline.id}.{series.name}[{index}]")
    if not baseline.numeric_series:
        # No numeric series in the baseline: exit-code equivalence only.
        return (1.0 if baseline.exit_code == after.exit_code else 0.0), drifted
    return (matched / total if total else 1.0), drifted


def _structural_leaves(value: Any, prefix: str) -> dict[str, Any]:
    leaves: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            leaves.update(_structural_leaves(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            leaves.update(_structural_leaves(item, f"{prefix}[{index}]"))
    else:
        leaves[prefix or "<root>"] = value
    return leaves


def _compare_structural(
    baseline: CaseFingerprint, after: CaseFingerprint, tolerance: Tolerances
) -> tuple[float, list[str]]:
    drifted: list[str] = []
    if baseline.exit_code != after.exit_code:
        drifted.append(f"{baseline.id}.exit_code")
    base_leaves = _structural_leaves(baseline.structural, "")
    after_leaves = _structural_leaves(after.structural, "")
    total = 0
    matched = 0
    for key, value in base_leaves.items():
        total += 1
        if key not in after_leaves:
            drifted.append(f"{baseline.id}.structural.{key}:missing")
            continue
        other = after_leaves[key]
        if isinstance(value, (int, float)) and isinstance(other, (int, float)) and not isinstance(value, bool):
            if abs(float(value) - float(other)) <= tolerance.eps_abs + tolerance.eps_rel * abs(float(other)):
                matched += 1
            else:
                drifted.append(f"{baseline.id}.structural.{key}")
        elif value == other and type(value) is type(other):
            matched += 1
        else:
            drifted.append(f"{baseline.id}.structural.{key}")
    for key in after_leaves:
        if key not in base_leaves:
            drifted.append(f"{baseline.id}.structural.{key}:unexpected")
            total += 1
    if not base_leaves:
        return (1.0 if baseline.exit_code == after.exit_code and not drifted else 0.0), drifted
    return matched / total, drifted


def compare(
    baseline: Any,
    after: Any,
    tolerances: Tolerances | Mapping[str, Any] | None = None,
) -> BehaviorResult:
    """Compare a captured fingerprint against a baseline.

    Returns compatibility=None when there is no usable baseline.
    """

    base = _as_fingerprint(baseline)
    current = _as_fingerprint(after)
    if current is None:
        raise ValueError("after fingerprint is required")
    if base is None or not base.cases:
        return BehaviorResult(
            compatibility=None,
            per_case=[],
            drifted_fields=["baseline.missing"],
            baseline_source=None,
            degraded=True,
        )

    base_cases = {case.id: case for case in base.cases}
    after_cases = {case.id: case for case in current.cases}
    comparisons: list[CaseComparison] = []
    all_drifted: list[str] = []

    for case_id, base_case in base_cases.items():
        tolerance = _tolerance_for(tolerances, case_id)
        candidate = after_cases.get(case_id)
        if candidate is None:
            comparisons.append(
                CaseComparison(
                    case_id=case_id,
                    ok=False,
                    compatibility=0.0,
                    drifted_fields=[f"{case_id}:missing_after_fingerprint"],
                    mode=tolerance.mode,
                )
            )
            all_drifted.append(f"{case_id}:missing_after_fingerprint")
            continue
        if tolerance.mode == "numeric":
            compatibility, drifted = _compare_numeric(base_case, candidate, tolerance)
        elif tolerance.mode == "structural":
            compatibility, drifted = _compare_structural(base_case, candidate, tolerance)
        else:
            compatibility, drifted = _compare_exact(base_case, candidate)
        comparisons.append(
            CaseComparison(
                case_id=case_id,
                ok=compatibility == 1.0,
                compatibility=compatibility,
                drifted_fields=drifted,
                mode=tolerance.mode,
            )
        )
        all_drifted.extend(drifted)

    for case_id in after_cases:
        if case_id not in base_cases:
            all_drifted.append(f"{case_id}:unexpected_after_case")

    overall = sum(item.compatibility for item in comparisons) / len(comparisons)
    return BehaviorResult(
        compatibility=round(overall, 6),
        per_case=comparisons,
        drifted_fields=all_drifted,
        baseline_source=base.baseline_source,
        degraded=False,
    )


__all__ = ["CaseComparison", "BehaviorResult", "compare"]
