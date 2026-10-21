"""Local (serverless) full-pipeline assembly (T-CLI-02).

Wires the sandbox, dependency installer, repair loop, behaviour capture,
scoring and capsule builder into one run.  assemble_pipeline(config, ports) is
the reusable factory the backend worker can call with its own ports; the CLI
--local path builds the same object with a DockerExecutionPort (or the local
test substitute when Docker is unavailable).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from revive_core.archaeology import extract_evidence, fetch_repo, infer_genome
from revive_core.behavior.capture import (
    BehaviorPlan,
    CaseSpec,
    Fingerprint,
    capture,
    select_baseline,
)
from revive_core.behavior.compare import BehaviorResult, compare
from revive_core.capsule.builder import RunState, build_capsule
from revive_core.sandbox.dep_solver import (
    InstallOutcome,
    lock_text,
    resolve_and_install,
)
from revive_core.sandbox.dockerfile_template import render_dockerfile
from revive_core.sandbox.executor import EventPort
from revive_core.sandbox.image_matrix import ImagePlan, Unsupported, plan_image
from revive_core.sandbox.patch_flow import (
    MAX_ITERATIONS,
    PatchOutcome,
    PatchRecorder,
    apply_and_verify,
)
from revive_core.sandbox.runner import StagePlan, StageResult, run_stage
from revive_core.scoring import ResurrectionScore, compute_score

from .jobs import EVENT_TYPES


@dataclass
class PipelineConfig:
    repo_url: str
    job_id: str = ""
    project_id: str = "local"
    work_root: str | None = None
    out_path: str | None = None
    timeout: float = 300.0
    keep_sandbox: bool = False
    budget_usd: float = 0.0
    max_iterations: int = MAX_ITERATIONS
    install_dependencies: bool = True
    capture_behavior: bool = True
    build_argv: list[str] | None = None
    test_argv: list[str] | None = None


@runtime_checkable
class RepairPolicy(Protocol):
    async def propose(self, error_fact: Any, attempt: int) -> Any: ...


class ScriptedRepairPolicy:
    """Deterministic repair policy for golden tests (fake-LLM replay)."""

    def __init__(self, proposals: list[Any]) -> None:
        self.proposals = list(proposals)
        self.calls = 0

    async def propose(self, error_fact: Any, attempt: int) -> Any:
        self.calls += 1
        if not self.proposals:
            return None
        return self.proposals.pop(0)


class LLMRepairPolicy:
    """Wraps T-AG-04's repairer; used when a real/fake provider is configured."""

    def __init__(self, provider: Any, workspace_manifest: dict[str, Any] | None = None) -> None:
        self.provider = provider
        self.workspace_manifest = workspace_manifest or {}

    async def propose(self, error_fact: Any, attempt: int) -> Any:
        from revive_agents.nodes.repairer import repair  # noqa: PLC0415

        fact = {
            "signature": getattr(error_fact, "signature", ""),
            "category": getattr(error_fact, "category", ""),
            "raw_excerpt": getattr(error_fact, "raw_excerpt", ""),
        }
        return await repair(fact, self.workspace_manifest, [], self.provider)


@dataclass
class PipelinePorts:
    execution: Any
    events: EventPort | None = None
    provider: Any = None
    repair_policy: RepairPolicy | None = None
    version_provider: Any = None


@dataclass
class PipelineResult:
    job_id: str
    status: str
    score: ResurrectionScore
    capsule_path: str | None
    events: list[dict[str, Any]] = field(default_factory=list)
    stages: dict[str, Any] = field(default_factory=dict)
    install: InstallOutcome | None = None
    patch_outcomes: list[PatchOutcome] = field(default_factory=list)
    behavior: BehaviorResult | None = None
    genome: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "score": self.score.to_dict(),
            "capsule_path": self.capsule_path,
            "events": list(self.events),
            "stages": self.stages,
            "install": self.install.to_dict() if self.install else None,
            "patch_outcomes": [item.to_dict() for item in self.patch_outcomes],
            "behavior": self.behavior.to_dict() if self.behavior else None,
            "genome": self.genome,
            "source_path": self.source_path,
        }


class LocalPipeline:
    def __init__(self, config: PipelineConfig, ports: PipelinePorts) -> None:
        self.config = config
        self.ports = ports
        self.events: list[dict[str, Any]] = []
        self.job_id = config.job_id or f"local-{uuid.uuid4().hex[:8]}"

    # -- event helpers ---------------------------------------------------
    async def emit(self, kind: str, payload: Mapping[str, Any] | None = None) -> None:
        if kind not in EVENT_TYPES:
            raise ValueError(f"unknown job-event type {kind!r}")
        event = {
            "type": kind,
            "payload": dict(payload or {}),
            "ts": datetime.now(UTC).isoformat(),
        }
        self.events.append(event)
        if self.ports.events is not None:
            await self.ports.events.emit(event)

    # -- source / genome -------------------------------------------------
    def _prepare_source(self) -> Path:
        root = Path(self.config.work_root) if self.config.work_root else Path.cwd()
        root.mkdir(parents=True, exist_ok=True)
        target = root / "src"
        if target.exists() and any(target.iterdir()):
            return target
        mirror = fetch_repo(self.config.repo_url, target)
        self.source_commit = mirror.head_commit
        return mirror.path

    def _genome(self, source: Path) -> dict[str, Any]:
        evidence = extract_evidence(source)
        genome = infer_genome(evidence)
        return json.loads(genome.model_dump_json())

    # -- behaviour -------------------------------------------------------
    def _behavior_plan(self, source: Path) -> BehaviorPlan:
        cases: list[CaseSpec] = []
        expected_dir = source / "tests" / "expected"
        tests_dir = source / "tests"
        package = detect_package(source)
        if package:
            cases.append(
                CaseSpec(
                    id="import",
                    argv=["python", "-c", f"import {package}"],
                    tolerance=__import__("revive_core.behavior.capture", fromlist=["Tolerances"]).Tolerances(
                        mode="exact"
                    ),
                )
            )
        if tests_dir.is_dir():
            cases.append(
                CaseSpec(
                    id="pytest",
                    argv=list(self.config.test_argv or ["python", "-m", "pytest", "-x", "-q"]),
                    tolerance=__import__("revive_core.behavior.capture", fromlist=["Tolerances"]).Tolerances(
                        mode="exact"
                    ),
                )
            )
        del expected_dir
        return BehaviorPlan(cases=cases, plan_ref="tests/behavior-plan.json")

    def _repo_expected_baseline(self, source: Path, plan: BehaviorPlan) -> Fingerprint | None:
        expected_dir = source / "tests" / "expected"
        if not expected_dir.is_dir():
            return None
        cases = []
        from revive_core.behavior.capture import CaseFingerprint  # noqa: PLC0415

        for case in plan.cases:
            candidate = expected_dir / f"{case.id}.txt"
            if not candidate.is_file():
                return None
            payload = candidate.read_text(encoding="utf-8", errors="replace")
            cases.append(
                CaseFingerprint(
                    id=case.id,
                    exit_code=0,
                    stdout_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                    argv=list(case.argv),
                )
            )
        return Fingerprint(
            plan_ref=plan.plan_ref,
            captured_at=self._started_at,
            cases=cases,
            baseline_source={
                "priority": 1,
                "kind": "repo_expected_outputs",
                "reference": "tests/expected/",
            },
        )

    async def _behavior(self, handle: Any, source: Path) -> tuple[BehaviorResult | None, Fingerprint | None]:
        plan = self._behavior_plan(source)
        if not plan.cases:
            return None, None
        after = await capture(handle, plan, events=self.ports.events, clock=self._started_at)
        baseline_fp = self._repo_expected_baseline(source, plan)
        choice = select_baseline(repo_expected=baseline_fp)
        result = compare(choice.fingerprint, after)
        if choice.fingerprint is not None:
            result.baseline_source = choice.provenance()
        await self.emit(
            "behavior.compared",
            {
                "compatibility": result.compatibility,
                "baseline_kind": choice.kind,
                "drifted_fields": result.drifted_fields,
            },
        )
        return result, after

    # -- run -------------------------------------------------------------
    async def run(self) -> PipelineResult:
        self._started_at = datetime.now(UTC).isoformat()
        await self.emit("job.queued", {"repo": self.config.repo_url, "mode": "local"})

        source = self._prepare_source()
        await self.emit("archaeology.started", {"path": str(source)})
        if isinstance(self.ports.repair_policy, LLMRepairPolicy):
            from revive_agents.nodes.repairer import workspace_manifest  # noqa: PLC0415

            self.ports.repair_policy.workspace_manifest = workspace_manifest(source)
        genome = self._genome(source)
        await self.emit("env.inferred", {"python": genome.get("python", {}).get("version")})

        plan = plan_image(genome)
        if isinstance(plan, Unsupported):
            dockerfile = f"# unsupported environment: {plan.reason}\n"
            image_plan: ImagePlan | None = None
        else:
            dockerfile = render_dockerfile(plan)
            image_plan = plan

        handle = await self.ports.execution.ensure_env(genome)
        if image_plan is not None:
            handle.image_plan = image_plan
        await self.emit("sandbox.created", {"backend": handle.backend, "ws": handle.ws_path})

        install: InstallOutcome | None = None
        if self.config.install_dependencies:
            install = await resolve_and_install(
                handle,
                genome,
                provider=self.ports.version_provider,
                events=self.ports.events,
                timeout=self.config.timeout,
            )

        stage_plan = StagePlan(
            package_name=detect_package(source) or "",
            tests_dir="tests",
            build_argv=list(self.config.build_argv or ["python", "-m", "pip", "install", "-e", "."]),
            test_argv=list(self.config.test_argv or ["python", "-m", "pytest", "-x", "-q"]),
            timeout=self.config.timeout,
        )
        recorder = PatchRecorder()
        stages: dict[str, Any] = {}
        build_result: StageResult = await run_stage(handle, "build", stage_plan)
        stages["build"] = build_result.to_dict()
        if not build_result.ok:
            await self.emit(
                "build.failed",
                {"signature": getattr(build_result.error_fact, "signature", "unknown")},
            )

        attempts = 0
        patch_outcomes: list[PatchOutcome] = []
        applied_tokens: set[str] = set()
        while not build_result.ok and attempts < self.config.max_iterations:
            attempts += 1
            policy = self.ports.repair_policy
            if policy is None:
                break
            proposal = await policy.propose(build_result.error_fact, attempts)
            if proposal is None:
                break
            await self.emit("repair.attempt", {"attempt": attempts})
            outcome = await apply_and_verify(
                handle,
                proposal,
                rerun=lambda: run_stage(handle, "build", stage_plan),
                events=self.ports.events,
                recorder=recorder,
                applied_tokens=applied_tokens,
            )
            patch_outcomes.append(outcome)
            if outcome.rolled_back:
                break
            build_result = outcome.rerun_result or build_result
            stages[f"build_attempt_{attempts}"] = build_result.to_dict() if hasattr(build_result, "to_dict") else {}
        if build_result.ok and patch_outcomes:
            await self.emit("repair.applied", {"patches": len(patch_outcomes)})

        test_result: StageResult = await run_stage(handle, "test", stage_plan)
        stages["test"] = test_result.to_dict()
        if not test_result.ok:
            await self.emit(
                "build.failed",
                {
                    "stage": "test",
                    "signature": getattr(test_result.error_fact, "signature", "unknown"),
                },
            )

        behavior_result, fingerprint = await self._behavior(handle, source)

        deps_total = 0
        deps_ok = 0
        if install is not None:
            deps_total = len(install.locked) + len(install.failures)
            deps_ok = len(install.locked)
        deps_ratio = (deps_ok / deps_total) if deps_total else 1.0
        score = compute_score(
            runtime_ok=True,
            deps_ratio=deps_ratio,
            build_ok=build_result.ok,
            tests_pass_ratio=1.0 if test_result.ok else 0.0,
            behavior_compat=behavior_result.compatibility if behavior_result else None,
            repro_verified=False,
        )
        await self.emit("score.computed", {"total": score.total, "status": score.status})

        run_state = RunState(
            job_id=self.job_id,
            source_repo=_repo_url(self.config.repo_url, source),
            source_commit=getattr(self, "source_commit", "") or _git_head(source),
            genome=genome,
            dockerfile=dockerfile,
            score=score,
            dependencies_lock=lock_text(install) if install else "",
            patches=[(name, diff) for name, diff in recorder.entries],
            behavior_plan=self._behavior_plan(source).to_dict(),
            fingerprints=fingerprint.to_dict() if fingerprint else None,
            behavior_compatibility=behavior_result.compatibility if behavior_result else None,
            status=score.status,
            provenance={
                "mode": "local",
                "execution_backend": handle.backend,
                "image_plan": image_plan.to_dict() if image_plan else None,
            },
            evidence=[f"archaeology:{source}"],
            created_at=self._started_at,
            source_tree=source,
        )
        capsule = build_capsule(run_state, self.config.out_path, verify=True)
        await self.emit("capsule.created", {"path": str(capsule)})

        terminal = "job.succeeded" if (build_result.ok and test_result.ok) else "job.failed"
        await self.emit(terminal, {"status": score.status, "capsule": str(capsule)})

        return PipelineResult(
            job_id=self.job_id,
            status=score.status,
            score=score,
            capsule_path=str(capsule),
            events=list(self.events),
            stages=stages,
            install=install,
            patch_outcomes=patch_outcomes,
            behavior=behavior_result,
            genome=genome,
            source_path=str(source),
        )


def detect_package(source: Path) -> str | None:
    """Best-effort import name of the project under source/."""

    src = source / "src"
    for base in (src, source):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and (child / "__init__.py").is_file() and not child.name.startswith("."):
                if child.name in {"tests", "test", "docs", "examples"}:
                    continue
                return child.name
    return None


def _git_head(source: Path) -> str:
    try:
        from revive_core.gitutil import run_git

        result = run_git(["-C", str(source), "rev-parse", "HEAD"], check=False)
        return result.stdout.strip()
    except Exception:
        return "0000000"


def _repo_url(repo_url: str, source: Path) -> str:
    if repo_url.startswith("http"):
        return repo_url
    return source.resolve().as_uri()


def assemble_pipeline(config: PipelineConfig, ports: PipelinePorts) -> LocalPipeline:
    """Reusable factory (backend worker and CLI both use this)."""

    return LocalPipeline(config, ports)


from revive_core.sandbox.patch_flow import MAX_ITERATIONS  # noqa: E402  (re-export for callers)

__all__ = [
    "PipelineConfig",
    "PipelinePorts",
    "PipelineResult",
    "LocalPipeline",
    "RepairPolicy",
    "ScriptedRepairPolicy",
    "LLMRepairPolicy",
    "assemble_pipeline",
    "detect_package",
    "MAX_ITERATIONS",
]
