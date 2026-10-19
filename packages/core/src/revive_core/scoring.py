"""The one and only Resurrection Score implementation (T-CAP-01).

Weights are read from resurrection-score.schema.json (x-weights); the rule for
a missing behaviour baseline is read from the same schema
(x-behavior-null-degradation).  No CLI, Web or benchmark code may re-implement
this formula - they must call compute_score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import schemas

COMPONENTS: tuple[str, ...] = (
    "runtime",
    "dependencies",
    "build",
    "tests",
    "behavior",
    "reproducibility",
)

ALIVE_THRESHOLD = 85.0
PARTIAL_THRESHOLD = 60.0


def _clamp_ratio(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def schema_weights() -> dict[str, float]:
    """Read the component weights from the frozen schema."""

    raw = schemas.load_schema("score").get("x-weights", {})
    return {name: float(raw[name]) for name in COMPONENTS}


def degradation_rule() -> str:
    """The behaviour=null rule, read from the schema annotation."""

    annotation = schemas.load_schema("score").get("x-behavior-null-degradation", {})
    return str(annotation.get("rule", "renormalize_remaining_weights"))


def _effective_weights(behavior_present: bool) -> dict[str, float]:
    weights = schema_weights()
    if behavior_present:
        return weights
    if degradation_rule() != "renormalize_remaining_weights":  # pragma: no cover
        return weights
    remaining = {name: weight for name, weight in weights.items() if name != "behavior"}
    total = sum(remaining.values())
    if total <= 0:  # pragma: no cover - defensive
        return remaining
    return {name: weight / total for name, weight in remaining.items()}


@dataclass
class ResurrectionScore:
    """Exactly the seven numeric fields of resurrection-score.schema.json."""

    runtime: float
    dependencies: float
    build: float
    tests: float
    behavior: float
    reproducibility: float
    total: float
    status: str = "partial"
    behavior_baseline_present: bool = True
    degraded: bool = False
    weights_used: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, float]:
        return {
            "runtime": self.runtime,
            "dependencies": self.dependencies,
            "build": self.build,
            "tests": self.tests,
            "behavior": self.behavior,
            "reproducibility": self.reproducibility,
            "total": self.total,
        }

    def validate(self) -> None:
        schemas.validate(self.to_dict(), "score")

    @property
    def components(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in COMPONENTS}


def map_status(total: float, *, repro_verified: bool, behavior_present: bool) -> str:
    """total>=85 and reproducibility -> alive; 60-84 or no baseline -> partial; <60 -> dead."""

    if total < PARTIAL_THRESHOLD:
        return "dead"
    if total >= ALIVE_THRESHOLD and repro_verified and behavior_present:
        return "alive"
    return "partial"


def compute_score(
    runtime_ok: bool | float,
    deps_ratio: float,
    build_ok: bool | float,
    tests_pass_ratio: float,
    behavior_compat: float | None,
    repro_verified: bool,
    *,
    runtime_ratio: float | None = None,
) -> ResurrectionScore:
    """Compute the six-component score and self-validate against the schema."""

    if isinstance(runtime_ok, bool):
        runtime_component = 100.0 if runtime_ok else 0.0
    else:
        runtime_component = _clamp_ratio(runtime_ok) * 100.0
    if runtime_ratio is not None:
        runtime_component = _clamp_ratio(runtime_ratio) * 100.0
    if isinstance(build_ok, bool):
        build_component = 100.0 if build_ok else 0.0
    else:
        build_component = _clamp_ratio(build_ok) * 100.0

    behavior_present = behavior_compat is not None
    components: dict[str, float] = {
        "runtime": runtime_component,
        "dependencies": _clamp_ratio(deps_ratio) * 100.0,
        "build": build_component,
        "tests": _clamp_ratio(tests_pass_ratio) * 100.0,
        "behavior": _clamp_ratio(behavior_compat) * 100.0 if behavior_present else 0.0,
        "reproducibility": 100.0 if repro_verified else 0.0,
    }

    weights = _effective_weights(behavior_present)
    total = sum(components[name] * weights.get(name, 0.0) for name in COMPONENTS)
    total = round(max(0.0, min(100.0, total)), 2)

    score = ResurrectionScore(
        runtime=round(components["runtime"], 2),
        dependencies=round(components["dependencies"], 2),
        build=round(components["build"], 2),
        tests=round(components["tests"], 2),
        behavior=round(components["behavior"], 2),
        reproducibility=round(components["reproducibility"], 2),
        total=total,
        status=map_status(total, repro_verified=repro_verified, behavior_present=behavior_present),
        behavior_baseline_present=behavior_present,
        degraded=not behavior_present,
        weights_used={name: round(weight, 6) for name, weight in weights.items()},
    )
    score.validate()
    return score


__all__ = [
    "COMPONENTS",
    "ALIVE_THRESHOLD",
    "PARTIAL_THRESHOLD",
    "ResurrectionScore",
    "compute_score",
    "map_status",
    "schema_weights",
    "degradation_rule",
]
