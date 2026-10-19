"""Environment genome builder: evidence in, schema-valid genome out.

Pure, deterministic Python. No LLM, no network unless a PypiClient is supplied.
Every conclusion carries at least one evidence item; conflicting evidence caps
confidence at rules.CONFLICT_CONFIDENCE_CAP and adds an explanatory note.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from ..models.genome import Dependency, EnvironmentGenome, Evidence, Inference
from . import rules
from .evidence import EvidenceItem, EvidenceReference

log = structlog.get_logger(__name__)


@dataclass
class _PythonSignal:
    tier: str
    priority: int
    version: str
    confidence: float
    item: EvidenceItem
    versions: tuple[str, ...]


@dataclass
class _DepRecord:
    name: str
    version: str
    specifier: str
    pinned: bool
    lock: bool
    source: str
    line: int | None
    item: EvidenceItem
    priority: int


def _coerce(item: Any) -> EvidenceItem | None:
    if isinstance(item, EvidenceItem):
        return item
    if item is None:
        return None
    if isinstance(item, dict):
        source_kind = item.get("source_kind", "inference")
        reference = item.get("reference", {})
        if isinstance(reference, dict):
            ref = EvidenceReference(
                file=str(reference.get("file", "unknown")),
                line_start=reference.get("line_start"),
                line_end=reference.get("line_end"),
                commit_sha=reference.get("commit_sha"),
                tag=reference.get("tag"),
            )
        else:
            ref = EvidenceReference(file=str(reference))
        return EvidenceItem(
            source_kind=source_kind,
            reference=ref,
            facts=dict(item.get("facts") or {}),
            note=item.get("note"),
        )
    if hasattr(item, "facts") and hasattr(item, "source_kind"):
        reference = getattr(item, "reference", None)
        if isinstance(reference, EvidenceReference):
            ref = reference
        elif isinstance(reference, dict):
            ref = EvidenceReference(file=str(reference.get("file", "unknown")))
        else:
            ref = EvidenceReference(file=str(reference or "unknown"))
        return EvidenceItem(
            source_kind=getattr(item, "source_kind", "inference"),
            reference=ref,
            facts=dict(getattr(item, "facts", {}) or {}),
            note=getattr(item, "note", None),
        )
    return None


def _normalize(evidence: Any) -> list[EvidenceItem]:
    if evidence is None:
        return []
    out: list[EvidenceItem] = []
    for item in evidence:
        coerced = _coerce(item)
        if coerced is not None:
            out.append(coerced)
    return out


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in value.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _min_version(versions: tuple[str, ...] | list[str]) -> str:
    return min(versions, key=_version_key)


def _python_signals(items: list[EvidenceItem]) -> list[_PythonSignal]:
    signals: list[_PythonSignal] = []
    for item in items:
        facts = item.facts if isinstance(item.facts, dict) else {}
        if facts.get("python_requires"):
            version = str(facts["python_requires"])
            signals.append(
                _PythonSignal(
                    "python_requires",
                    0,
                    version,
                    rules.PYTHON_CONFIDENCE["python_requires"],
                    item,
                    (version,),
                )
            )
        ci_versions = facts.get("python_versions")
        if ci_versions and item.source_kind == "ci_config":
            versions = tuple(str(v) for v in ci_versions)
            if versions:
                signals.append(
                    _PythonSignal(
                        "ci_matrix",
                        1,
                        _min_version(versions),
                        rules.PYTHON_CONFIDENCE["ci_matrix"],
                        item,
                        versions,
                    )
                )
        if facts.get("base_image") and facts.get("python_version"):
            version = str(facts["python_version"])
            signals.append(
                _PythonSignal(
                    "dockerfile_base",
                    2,
                    version,
                    rules.PYTHON_CONFIDENCE["dockerfile_base"],
                    item,
                    (version,),
                )
            )
        classifier_versions = facts.get("python_classifiers")
        if classifier_versions:
            versions = tuple(str(v) for v in classifier_versions)
            if versions:
                signals.append(
                    _PythonSignal(
                        "classifiers",
                        3,
                        _min_version(versions),
                        rules.PYTHON_CONFIDENCE["classifiers"],
                        item,
                        versions,
                    )
                )
        doc_versions = facts.get("python_versions")
        if doc_versions and item.source_kind == "doc":
            versions = tuple(str(v) for v in doc_versions)
            if versions:
                signals.append(
                    _PythonSignal(
                        "readme_keywords",
                        4,
                        _min_version(versions),
                        rules.PYTHON_CONFIDENCE["readme_keywords"],
                        item,
                        versions,
                    )
                )
    return signals


def _detect_conflicts(primary: _PythonSignal, signals: list[_PythonSignal]) -> list[str]:
    reasons: list[str] = []
    for tier in ("readme_keywords",):
        if primary.tier != tier:
            continue
        versions: set[str] = set()
        for signal in signals:
            if signal.tier == tier:
                versions.update(signal.versions)
        if len(versions) > 1:
            reasons.append(f"{rules.PYTHON_RULE_LABEL[tier]} lists multiple versions {sorted(versions)}")
    primary_major = primary.version.split(".")[0]
    for signal in signals:
        if signal is primary:
            continue
        if signal.version.split(".")[0] != primary_major:
            reasons.append(f"{signal.tier}={signal.version} conflicts with {primary.tier}={primary.version}")
    return reasons


def _signal_evidence(signals: list[_PythonSignal]) -> list[Evidence]:
    seen: set[str] = set()
    out: list[Evidence] = []
    for signal in signals:
        key = signal.item.ref_string()
        if key in seen:
            continue
        seen.add(key)
        kind = "inference" if signal.tier == "readme_keywords" else signal.item.source_kind
        out.append(Evidence(source_kind=kind, reference=key, note=signal.item.note))
    return out


def _build_python(items: list[EvidenceItem]) -> tuple[Inference, float]:
    signals = _python_signals(items)
    if not signals:
        evidence = [
            Evidence(
                source_kind="inference",
                reference="repo",
                note="no python version signal found in manifests, CI, Dockerfile or docs",
            )
        ]
        return Inference(
            version=None, confidence=rules.NEGATIVE_CONFIDENCE["python"], evidence=evidence
        ), rules.NEGATIVE_CONFIDENCE["python"]

    primary = min(signals, key=lambda signal: (signal.priority, -signal.confidence))
    conflicts = _detect_conflicts(primary, signals)
    confidence = primary.confidence
    evidence = _signal_evidence(signals)
    if conflicts:
        confidence = min(confidence, rules.CONFLICT_CONFIDENCE_CAP)
        evidence.append(
            Evidence(
                source_kind="inference",
                reference=primary.item.ref_string(),
                note="conflicting evidence: " + "; ".join(conflicts),
            )
        )
    image = None
    for signal in signals:
        base = signal.item.facts.get("base_image") if isinstance(signal.item.facts, dict) else None
        if isinstance(base, str):
            image = base
            break
    inference = Inference(version=primary.version, image=image, confidence=confidence, evidence=evidence)
    return inference, confidence


def _merge_dependencies(items: list[EvidenceItem]) -> dict[str, _DepRecord]:
    records: dict[str, _DepRecord] = {}
    for item in items:
        deps = item.facts.get("dependencies") if isinstance(item.facts, dict) else None
        if not isinstance(deps, list):
            continue
        is_lock = bool(item.facts.get("lock")) or item.source_kind == "lock"
        for dep in deps:
            if not isinstance(dep, dict):
                continue
            name = str(dep.get("name") or "").strip()
            if not name:
                continue
            version = str(dep.get("version") or "")
            lock = is_lock
            pinned = bool(dep.get("pinned")) or bool(version)
            priority = 0 if lock else (1 if pinned else 2)
            existing = records.get(name)
            if existing is None or priority < existing.priority:
                records[name] = _DepRecord(
                    name=name,
                    version=version,
                    specifier=str(dep.get("specifier") or ""),
                    pinned=pinned,
                    lock=lock,
                    source=str(dep.get("source") or item.source_kind),
                    line=dep.get("line") if isinstance(dep.get("line"), int) else None,
                    item=item,
                    priority=priority,
                )
            elif priority == existing.priority and version and not existing.version:
                existing.version = version
    return records


def _inference_evidence(item: EvidenceItem, note: str) -> Evidence:
    return Evidence(source_kind="inference", reference=item.ref_string(), note=note)


def _build_dependencies(
    records: dict[str, _DepRecord],
    *,
    pypi: Any,
    cutoff: datetime,
    offline: bool,
) -> tuple[list[Dependency], float]:
    dependencies: list[Dependency] = []
    confidences: list[float] = []
    for name in sorted(records):
        record = records[name]
        evidence = [
            Evidence(
                source_kind=record.item.source_kind,
                reference=record.item.ref_string(),
                note=record.item.note,
            )
        ]
        if record.lock:
            version = record.version or "*"
            source = "lock"
            confidence = rules.DEPENDENCY_CONFIDENCE["lock"]
        elif record.version:
            version = record.version
            source = record.source or "manifest"
            confidence = rules.DEPENDENCY_CONFIDENCE["pinned"]
        else:
            resolved = None
            if pypi is not None and not offline:
                try:
                    resolved = pypi.latest_before(name, cutoff)
                except Exception as exc:  # noqa: BLE001 - a lookup failure must not abort inference
                    log.warning("inference.pypi_failed", package=name, error=str(exc))
            if resolved is not None:
                version = resolved.version
                source = "pypi"
                confidence = rules.DEPENDENCY_CONFIDENCE["pypi"]
                evidence.append(
                    Evidence(
                        source_kind="release_artifact",
                        reference=f"pypi:{name}",
                        note=f"latest release before {cutoff.date().isoformat()}",
                    )
                )
            else:
                version = "*"
                source = "inference"
                confidence = rules.DEPENDENCY_CONFIDENCE["inference"]
                evidence.append(
                    _inference_evidence(
                        record.item,
                        "unresolved: no lock, no == pin and no historical PyPI resolution",
                    )
                )
        dependencies.append(
            Dependency(name=name, version=version, source=source, confidence=confidence, evidence=evidence)
        )
        confidences.append(confidence)
    field_confidence = sum(confidences) / len(confidences) if confidences else rules.NEGATIVE_CONFIDENCE["dependencies"]
    return dependencies, field_confidence


def _build_os(items: list[EvidenceItem]) -> tuple[Inference, float]:
    for item in items:
        facts = item.facts if isinstance(item.facts, dict) else {}
        if not facts.get("base_image"):
            continue
        image = str(facts["base_image"])
        distro = facts.get("os_distro")
        confidence = 0.80 if distro else 0.55
        evidence = [Evidence(source_kind=item.source_kind, reference=item.ref_string(), note=item.note)]
        return Inference(
            version=str(distro) if distro else None,
            image=image,
            confidence=confidence,
            evidence=evidence,
        ), confidence
    confidence = rules.NEGATIVE_CONFIDENCE["os"]
    evidence = [Evidence(source_kind="inference", reference="repo", note="no Dockerfile base image evidence")]
    return Inference(version=None, confidence=confidence, evidence=evidence), confidence


def _build_cuda(items: list[EvidenceItem]) -> tuple[Inference, float]:
    for item in items:
        facts = item.facts if isinstance(item.facts, dict) else {}
        cuda_version = facts.get("cuda_version")
        if not cuda_version:
            continue
        evidence = [Evidence(source_kind=item.source_kind, reference=item.ref_string(), note=item.note)]
        image = facts.get("base_image")
        return (
            Inference(
                version=str(cuda_version),
                image=str(image) if image else None,
                confidence=0.90,
                evidence=evidence,
            ),
            0.90,
        )
    confidence = rules.NEGATIVE_CONFIDENCE["cuda"]
    evidence = [Evidence(source_kind="inference", reference="repo", note="no CUDA signal in Dockerfile")]
    return Inference(version=None, confidence=confidence, evidence=evidence), confidence


def _overall_confidence(fields: dict[str, float]) -> float:
    total_weight = 0.0
    accumulator = 0.0
    for name, weight in rules.FIELD_WEIGHTS.items():
        confidence = min(max(fields.get(name, rules.NEGATIVE_CONFIDENCE.get(name, 0.1)), 1e-6), 1.0)
        accumulator += weight * math.log(confidence)
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    value = math.exp(accumulator / total_weight)
    return max(0.0, min(1.0, value))


def infer_genome(
    evidence: Any,
    timeline: Any = None,
    pypi: Any = None,
    *,
    offline: bool = False,
) -> EnvironmentGenome:
    """Build a schema-valid EnvironmentGenome from evidence (and optional history)."""

    items = _normalize(evidence)
    cutoff = getattr(timeline, "last_activity", None) or datetime.now(UTC)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)

    python, python_confidence = _build_python(items)
    records = _merge_dependencies(items)
    dependencies, dependency_confidence = _build_dependencies(records, pypi=pypi, cutoff=cutoff, offline=offline)
    os_inference, os_confidence = _build_os(items)
    cuda_inference, cuda_confidence = _build_cuda(items)
    system_libs: list[Inference] = []

    overall = _overall_confidence(
        {
            "python": python_confidence,
            "dependencies": dependency_confidence,
            "os": os_confidence,
            "cuda": cuda_confidence,
            "system_libs": rules.NEGATIVE_CONFIDENCE["system_libs"],
        }
    )
    return EnvironmentGenome(
        python=python,
        os=os_inference,
        dependencies=dependencies,
        cuda=cuda_inference,
        system_libs=system_libs,
        overall_confidence=overall,
    )


__all__ = ["infer_genome"]
