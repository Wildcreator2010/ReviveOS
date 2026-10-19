"""Build / test / cli-smoke stage runner (T-SB-04).

The runner never decides how to fix anything: it executes one stage, turns a
non-zero exit into a core ErrorFact via the T-CORE-07 classifier and reports
the artifacts it produced.  Repair decisions belong to the agent layer.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..errors.classifiers import ErrorFact, classify
from ..errors.taxonomy import ErrorCategory
from .executor import DEFAULT_TIMEOUT, ArtifactRef, RunResult, SandboxHandle

Stage = Literal["build", "test", "cli_smoke"]

_SUSPECT_RE = re.compile(r'File "([^"]+)"')
_SIGNATURE_HINTS: dict[str, list[str]] = {
    "import_error": [
        "an import moved or was removed between Python versions; check stdlib moves "
        "(e.g. collections.Mapping -> collections.abc.Mapping in 3.10)",
    ],
    "module_not_found": ["a declared dependency is missing or was renamed"],
    "no_matching_distribution": ["no wheel/sdist for this interpreter; a fallback version may be needed"],
    "python_version_incompatible": ["the interpreter is outside the project's Requires-Python range"],
    "syntax_error": ["source uses syntax removed in this interpreter"],
}


@dataclass
class StagePlan:
    """Everything the runner needs to know about the project layout."""

    package_name: str = ""
    package_dirs: tuple[str, ...] = ()
    tests_dir: str = "tests"
    working_dir: str = "/workspace"
    build_argv: list[str] = field(default_factory=lambda: ["python", "-m", "pip", "install", "-e", "."])
    test_argv: list[str] = field(default_factory=lambda: ["python", "-m", "pytest", "-x", "-q"])
    timeout: float = DEFAULT_TIMEOUT
    tests_timeout: float = DEFAULT_TIMEOUT

    def import_smoke_argv(self) -> list[str]:
        target = self.package_name or (self.package_dirs[0] if self.package_dirs else ".")
        return ["python", "-c", f"import {target.replace('-', '_')}"]

    def module_smoke_argv(self) -> list[str]:
        target = self.package_name or (self.package_dirs[0] if self.package_dirs else ".")
        return ["python", "-m", target.replace("-", "_")]


@dataclass
class StageResult:
    stage: str
    ok: bool
    error_fact: ErrorFact | None = None
    artifacts: list[ArtifactRef] = field(default_factory=list)
    exit_code: int = 0
    tests_absent: bool = False
    degraded: bool = False
    run: RunResult | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "tests_absent": self.tests_absent,
            "degraded": self.degraded,
            "note": self.note,
            "error_fact": None
            if self.error_fact is None
            else {
                "category": self.error_fact.category,
                "signature": self.error_fact.signature,
                "suspect_files": list(self.error_fact.suspect_files),
                "hints": list(self.error_fact.hints),
            },
            "artifacts": [ref.to_dict() for ref in self.artifacts],
        }


def _artifacts_root(handle: SandboxHandle) -> Path | None:
    value = handle.meta.get("artifacts_dir")
    return Path(str(value)) if value else None


def read_ref_text(handle: SandboxHandle, ref: ArtifactRef | None, *, limit: int = 64_000) -> str:
    """Read a bounded slice of an artifact for classification purposes."""

    if ref is None:
        return ""
    root = _artifacts_root(handle)
    if root is None:
        return ""
    path = root / ref.path
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle_file:
            return handle_file.read(limit)
    except OSError:
        return ""


def _suspect_files(stderr_text: str) -> list[str]:
    seen: list[str] = []
    for match in _SUSPECT_RE.finditer(stderr_text):
        candidate = match.group(1).strip()
        if candidate and candidate not in seen and "site-packages" not in candidate:
            seen.append(candidate)
    return seen[:10]


def make_error_fact(stage: str, result: RunResult, stderr_text: str, stdout_text: str = "") -> ErrorFact:
    """Classify a failed execution into a core ErrorFact (T-CORE-07)."""

    if result.timed_out:
        return ErrorFact(
            category=ErrorCategory.R99,
            signature="timeout",
            suspect_files=[],
            hints=[f"stage {stage} exceeded its timeout; raise the stage budget or fix the hang"],
            raw_excerpt=(stderr_text or "")[:2000],
        )
    combined = stderr_text or stdout_text or ""
    fact = classify(stage, combined, result.exit_code)
    hints = list(fact.hints) or list(_SIGNATURE_HINTS.get(fact.signature, []))
    return ErrorFact(
        category=fact.category,
        signature=fact.signature,
        suspect_files=_suspect_files(combined),
        hints=hints,
        raw_excerpt=fact.raw_excerpt or combined[:2000],
    )


def _has_tests(handle: SandboxHandle, plan: StagePlan) -> bool:
    port = handle.port
    lister: Callable[[str], list[str]] | None = getattr(port, "list_dir", None)
    if lister is None:
        # A backend with no listing primitive (docker) tells us through meta.
        return bool(handle.meta.get("tests_present", False))
    try:
        entries = lister(plan.tests_dir)
    except OSError:
        return False
    return any(
        entry.startswith("test_") or entry.endswith("_test.py") or entry in {"tests.py", "conftest.py"}
        for entry in entries
    )


async def run_stage(handle: SandboxHandle, stage: Stage, plan: StagePlan) -> StageResult:
    """Execute one stage and translate a failure into an ErrorFact."""

    port = handle.port
    if port is None:
        raise RuntimeError("handle is not bound to an execution port")

    if stage == "build":
        argv = list(plan.build_argv)
        timeout = plan.timeout
    elif stage == "cli_smoke":
        argv = plan.module_smoke_argv() + ["--help"]
        timeout = plan.tests_timeout
    elif stage == "test":
        if _has_tests(handle, plan):
            argv = list(plan.test_argv)
            timeout = plan.tests_timeout
        else:
            # No tests directory: degrade to an import smoke and say so loudly.
            argv = plan.import_smoke_argv()
            timeout = plan.tests_timeout
            result = await port.run(stage, argv, timeout)
            stderr_text = read_ref_text(handle, result.stderr_ref)
            stdout_text = read_ref_text(handle, result.stdout_ref)
            error_fact = None if result.ok else make_error_fact(stage, result, stderr_text, stdout_text)
            return StageResult(
                stage=stage,
                ok=result.ok,
                error_fact=error_fact,
                artifacts=[ref for ref in (result.stdout_ref, result.stderr_ref) if ref],
                exit_code=result.exit_code,
                tests_absent=True,
                degraded=True,
                run=result,
                note="no tests directory found; ran an import smoke instead",
            )
    else:  # pragma: no cover - guarded by the Stage literal
        raise ValueError(f"unknown stage: {stage!r}")

    result = await port.run(stage, argv, timeout)
    stderr_text = read_ref_text(handle, result.stderr_ref)
    stdout_text = read_ref_text(handle, result.stdout_ref)
    error_fact = None if result.ok else make_error_fact(stage, result, stderr_text, stdout_text)
    return StageResult(
        stage=stage,
        ok=result.ok,
        error_fact=error_fact,
        artifacts=[ref for ref in (result.stdout_ref, result.stderr_ref) if ref],
        exit_code=result.exit_code,
        tests_absent=False,
        degraded=False,
        run=result,
    )


__all__ = [
    "Stage",
    "StagePlan",
    "StageResult",
    "run_stage",
    "make_error_fact",
    "read_ref_text",
]
