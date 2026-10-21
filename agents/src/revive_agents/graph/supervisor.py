"""Supervisor main graph (T-AG-06).

A deterministic async state machine that orchestrates
analyze -> infer -> (archaeologist if low confidence) -> build ->
{ok -> tests -> behavior -> score -> capsule | fail -> classify -> repair ->
build}.  Every dependency is injected: the sandbox-facing ExecutionPort and the
EventPort are protocols from revive_agents.ports, and the LLM-facing nodes are
callables.  There are no global singletons, no network calls and no polling
sleeps.

Guards: at most MAX_ITERATIONS build attempts, at most MAX_EVENTS job events
and a wall-clock deadline (REVIVE_JOB__TIMEOUT).  A BudgetExceeded anywhere
fails the job with reason 'budget'.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from revive_core.scoring import COMPONENTS, compute_score

from ..limits import MAX_ITERATIONS
from ..llm.base import BudgetExceeded
from ..ports import ExecutionCancelled
from .state import GraphState

MAX_EVENTS = 200
DEFAULT_JOB_TIMEOUT = 3600.0

EVENT_TYPES = (
    "job.queued",
    "archaeology.started",
    "archaeology.evidence",
    "env.inferred",
    "sandbox.created",
    "build.attempt",
    "build.failed",
    "repair.attempt",
    "repair.applied",
    "test.attempt",
    "behavior.captured",
    "behavior.compared",
    "score.computed",
    "capsule.created",
    "job.succeeded",
    "job.failed",
)


class _Timeout(Exception):
    pass


class _EventLimit(Exception):
    pass


def _get(deps: Any, name: str, default: Any = None) -> Any:
    if deps is None:
        return default
    if isinstance(deps, dict):
        return deps.get(name, default)
    return getattr(deps, name, default)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "to_dict", None)
    if callable(dump):
        return dict(dump())
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump())
    return {"value": str(value)}


def _ok(result: Any) -> bool:
    if result is None:
        return True
    if isinstance(result, bool):
        return result
    ok = getattr(result, "ok", None)
    if isinstance(ok, bool):
        return ok
    return bool(_as_dict(result).get("ok", True))


def _signature(error_fact: Any) -> str:
    return str(_as_dict(error_fact).get("signature", ""))


def _is_give_up(value: Any) -> bool:
    """Duck-typed so the graph never has to import the repairer node."""

    if type(value).__name__ == "GiveUp":
        return True
    return isinstance(value, dict) and "give_up" in value


def _env_timeout() -> float:
    raw = os.getenv("REVIVE_JOB__TIMEOUT")
    if raw is None or raw == "":
        return DEFAULT_JOB_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_JOB_TIMEOUT


@dataclass
class SupervisorDeps:
    execution: Any
    events: Any = None
    provider: Any = None
    archaeologist: Callable[..., Any] | None = None
    repair: Callable[..., Any] | None = None
    behavior_plan: Callable[..., Any] | None = None
    checkpointer: Any = None
    clock: Callable[[], float] = time.monotonic
    timeout: float | None = None
    max_events: int = MAX_EVENTS


class CompiledGraph:
    def __init__(self, deps: Any) -> None:
        self.deps = deps
        self.execution = _get(deps, "execution")
        self.events = _get(deps, "events")
        self.provider = _get(deps, "provider")
        self.archaeologist_fn = _get(deps, "archaeologist")
        self.repair_fn = _get(deps, "repair")
        self.behavior_plan_fn = _get(deps, "behavior_plan")
        self.behavior_fn = _get(deps, "behavior")
        self.capsule_fn = _get(deps, "capsule")
        self.checkpointer = _get(deps, "checkpointer")
        self.clock: Callable[[], float] = _get(deps, "clock", time.monotonic)
        timeout = _get(deps, "timeout")
        self.timeout = _env_timeout() if timeout is None else float(timeout)
        self.max_events = int(_get(deps, "max_events", MAX_EVENTS))
        self.emitted: list[dict[str, Any]] = []
        self._deadline = 0.0

    # -- infrastructure --------------------------------------------------
    def _check_deadline(self) -> None:
        if self.timeout and self.clock() - self._start > self.timeout:
            raise _Timeout()

    async def _emit(self, state: GraphState, type_: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if len(self.emitted) >= self.max_events:
            raise _EventLimit()
        event = {
            "id": str(uuid.uuid4()),
            "job_id": state.job_id,
            "project_id": _project_id(state),
            "ts": datetime.now(UTC).isoformat(),
            "type": type_,
            "payload": payload or {},
        }
        self.emitted.append(event)
        if self.events is not None:
            await self.events.emit(event)
        if self.checkpointer is not None:
            save = getattr(self.checkpointer, "save", None)
            if callable(save):
                result = save(state.job_id, state)
                if hasattr(result, "__await__"):
                    await result
        return event

    async def _force_emit(self, state: GraphState, type_: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        saved = self.max_events
        self.max_events = len(self.emitted) + 1
        try:
            return await self._emit(state, type_, payload)
        finally:
            self.max_events = saved

    # -- node steps ------------------------------------------------------
    def _low_confidence_fields(self, genome: Any) -> list[str]:
        data = _as_dict(genome)
        fields: list[str] = []
        for name in ("python", "os", "cuda"):
            section = data.get(name)
            if isinstance(section, dict):
                try:
                    confidence = float(section.get("confidence", 1.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                if confidence < 0.7:
                    fields.append(name)
        try:
            overall = float(data.get("overall_confidence", 1.0))
        except (TypeError, ValueError):
            overall = 0.0
        if overall < 0.7:
            fields.append("overall_confidence")
        return fields

    async def _run_archaeologist(self, state: GraphState) -> None:
        low = self._low_confidence_fields(state.genome)
        await self._emit(state, "archaeology.started", {"low_confidence_fields": low})
        if low and self.archaeologist_fn is not None:
            outcome = await self.archaeologist_fn(
                state.genome,
                low,
                _as_dict(state.project).get("evidence_corpus", []),
                self.provider,
            )
            genome = getattr(outcome, "genome", None)
            if genome is None and isinstance(outcome, (tuple, list)) and outcome:
                genome = outcome[0]
            if isinstance(genome, dict):
                state.genome = genome
            warnings = getattr(outcome, "warnings", []) or []
            await self._emit(
                state,
                "archaeology.evidence",
                {"low_confidence_fields": low, "warnings": list(warnings)},
            )

    async def _restore(self, token: Any) -> None:
        restore = getattr(self.execution, "restore_ws", None)
        if token is not None and callable(restore):
            await restore(token)

    async def _snapshot(self) -> Any:
        snapshot = getattr(self.execution, "snapshot_ws", None)
        return await snapshot() if callable(snapshot) else None

    async def _build_until_ok(self, state: GraphState, argv: Sequence[str]) -> bool:
        patch_snapshot: Any = None
        while True:
            self._check_deadline()
            state.build_attempts += 1
            state.iteration_counts["build"] = state.build_attempts
            await self._emit(state, "build.attempt", {"attempt": state.build_attempts})
            result = await self.execution.run("build", list(argv), self.timeout)
            if _ok(result):
                return True
            if _as_dict(result).get("timed_out") is True:
                await self._emit(
                    state,
                    "job.failed",
                    {"reason": "stage_timeout", "stage": "build", "attempt": state.build_attempts},
                )
                state.status = "failed"
                state.failure_reason = "stage_timeout"
                return False
            await self._emit(
                state,
                "build.failed",
                {
                    "attempt": state.build_attempts,
                    "reason": str(_as_dict(result).get("reason", "")),
                },
            )
            # The failed build ran against the patched tree; roll it back before the
            # next repair so retries never stack unverified diffs.
            if patch_snapshot is not None:
                await self._restore(patch_snapshot)
                patch_snapshot = None
            state.error_facts.append(_as_dict(result).get("error_fact") or _as_dict(result))
            if state.build_attempts >= MAX_ITERATIONS:
                await self._emit(
                    state,
                    "job.failed",
                    {
                        "reason": "repair_budget_exhausted",
                        "attempts": state.build_attempts,
                    },
                )
                state.status = "failed"
                state.failure_reason = "repair_budget_exhausted"
                return False
            await self._emit(state, "repair.attempt", {"attempt": state.build_attempts})
            self._check_deadline()
            if self.repair_fn is None:
                patch: Any = {"refused": "no repair node configured"}
            else:
                manifest = _as_dict(state.project).get("workspace_manifest", {})
                prior_attempts = [{"signature": _signature(fact), "accepted": False} for fact in state.error_facts[:-1]]
                patch = await self.repair_fn(state.error_facts[-1], manifest, prior_attempts, self.provider)
            if _is_give_up(patch):
                await self._emit(
                    state,
                    "job.failed",
                    {"reason": "repair_give_up", "detail": str(patch)},
                )
                state.status = "failed"
                state.failure_reason = "repair_give_up"
                return False
            state.patches.append(_as_dict(patch) or {"value": str(patch)})
            applied = False
            diff = _as_dict(patch).get("diff")
            if diff:
                snapshot = await self._snapshot()
                applied = _ok(await self.execution.apply_patch(diff))
                if applied:
                    patch_snapshot = snapshot
                else:
                    await self._restore(snapshot)
            await self._emit(state, "repair.applied", {"applied": applied, "attempt": state.build_attempts})

    def _plan(self, state: GraphState) -> Any:
        # No implicit behaviour plan: a repo without tests/importable package simply
        # has no behaviour evidence (score stays partial) instead of running a fake
        # "--plan" command and calling it captured.
        return state.behavior_plan or {"cases": []}

    # -- entry point -----------------------------------------------------
    async def ainvoke(self, state: GraphState | None = None) -> GraphState:
        state = state or GraphState()
        if not state.job_id:
            state.job_id = f"job-{uuid.uuid4().hex[:12]}"
        self.emitted = []
        self._start = self.clock()
        self._deadline = self._start + self.timeout if self.timeout else 0.0
        try:
            await self._emit(state, "job.queued", {"status": "queued"})
            await self._run_archaeologist(state)
            await self._emit(
                state,
                "env.inferred",
                {"confidence": _as_dict(state.genome).get("overall_confidence")},
            )
            handle = None
            if self.execution is not None:
                handle = await self.execution.ensure_env(state.genome)
                state.sandbox_handle = handle
            await self._emit(state, "sandbox.created", {})
            build_argv = _as_dict(state.project).get(
                "build_argv",
                ["python", "-m", "pip", "install", "--no-index", "--no-deps", "--no-build-isolation", "-e", "."],
            )
            built = await self._build_until_ok(state, build_argv)
            if not built:
                return state
            self._check_deadline()
            await self._emit(state, "test.attempt", {})
            test_argv = _as_dict(state.project).get("test_argv", ["python", "-m", "pytest", "-q"])
            test_result = await self.execution.run("test", list(test_argv), self.timeout)
            if not _ok(test_result):
                await self._emit(
                    state,
                    "job.failed",
                    {"reason": "tests_failed", "detail": str(_as_dict(test_result))},
                )
                state.status = "failed"
                state.failure_reason = "tests_failed"
                return state
            self._check_deadline()
            if self.behavior_plan_fn is not None:
                plan = await self.behavior_plan_fn(
                    _as_dict(state.project).get("source_tree_summary", {}),
                    str(_as_dict(state.project).get("readme_excerpt", "")),
                    _as_dict(state.project).get("examples_dir"),
                    _as_dict(state.project).get("tests_dir"),
                    self.provider,
                )
            else:
                plan = self._plan(state)
            state.behavior_plan = plan
            behavior_ok = False
            cases = len(_as_dict(plan).get("cases", []) or [])
            if self.behavior_fn is not None and cases:
                outcome = await self.behavior_fn(handle, plan)
                state.fingerprints = _as_dict(outcome).get("fingerprint")
                compatibility = _as_dict(outcome).get("compatibility")
                state.behavior_compatibility = float(compatibility) if isinstance(compatibility, (int, float)) else None
                behavior_ok = bool(_as_dict(outcome).get("matched"))
                await self._emit(state, "behavior.captured", {"cases": int(_as_dict(outcome).get("cases", cases))})
                await self._emit(state, "behavior.compared", {"matched": behavior_ok})
            state.score = self._score(state, test_result, {"ok": behavior_ok})
            await self._emit(
                state,
                "score.computed",
                {"total": _as_dict(state.score).get("total")},
            )
            state.status = "succeeded"
            if self.capsule_fn is not None:
                state.capsule_ref = await self.capsule_fn(state)
            else:
                state.capsule_ref = f"capsule://{state.job_id}"
            await self._emit(state, "capsule.created", {"capsule_ref": state.capsule_ref})
            await self._emit(state, "job.succeeded", {"status": "succeeded", "capsule_ref": state.capsule_ref})
            return state
        except _Timeout:
            await self._force_emit(state, "job.failed", {"reason": "timeout"})
            state.status = "failed"
            state.failure_reason = "timeout"
            return state
        except _EventLimit:
            await self._force_emit(
                state,
                "job.failed",
                {"reason": "event_budget_exhausted", "max_events": self.max_events},
            )
            state.status = "failed"
            state.failure_reason = "event_budget_exhausted"
            return state
        except BudgetExceeded as exc:
            await self._force_emit(state, "job.failed", {"reason": "budget", "detail": str(exc)})
            state.status = "failed"
            state.failure_reason = "budget"
            return state
        except ExecutionCancelled:
            # A caller-requested cancellation is not an internal error: let the job
            # owner record the terminal "cancelled" state.
            raise
        except Exception:
            await self._force_emit(state, "job.failed", {"reason": "internal_error"})
            state.status = "failed"
            state.failure_reason = "internal_error"
            return state

    @staticmethod
    def _score(state: GraphState, test_result: Any, behavior_result: Any) -> dict[str, Any]:
        tests_ok = _ok(test_result) and not _as_dict(state.project).get("tests_absent")
        behavior_ok = _ok(behavior_result)
        dependencies = _as_dict(state.genome).get("dependencies") or []
        confidences: list[float] = []
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            try:
                confidences.append(max(0.0, min(1.0, float(dependency.get("confidence", 0.0) or 0.0))))
            except (TypeError, ValueError):
                confidences.append(0.0)
        dependencies_ratio = sum(confidences) / len(confidences) if confidences else 1.0
        score = compute_score(
            runtime_ok=True,
            deps_ratio=dependencies_ratio,
            build_ok=True,
            tests_pass_ratio=1.0 if tests_ok else 0.0,
            behavior_compat=state.behavior_compatibility,
            repro_verified=False,
        )
        payload: dict[str, Any] = score.to_dict()
        payload["components"] = {name: float(payload[name]) for name in COMPONENTS}
        payload.update({"tests_ok": tests_ok, "behavior_ok": behavior_ok, "status": score.status})
        return payload


def _project_id(state: GraphState) -> str:
    project = state.project
    if isinstance(project, dict):
        return str(project.get("id") or project.get("project_id") or "")
    return str(getattr(project, "id", "") or "")


def build_graph(deps: Any) -> CompiledGraph:
    """Instantiate the supervisor with fully injected dependencies."""

    return CompiledGraph(deps)
