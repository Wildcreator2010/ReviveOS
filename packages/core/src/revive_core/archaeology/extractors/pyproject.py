"""Extract evidence from pyproject.toml (PEP 621 + a poetry subset)."""

from __future__ import annotations

import re
import tomllib
from pathlib import PurePosixPath
from typing import Any

from ..evidence import EvidenceItem, EvidenceReference, ExtractContext, inference_warning
from .common import (
    as_mapping,
    classifiers_to_python_versions,
    floor_python_version,
    make_dependency,
    parse_requirement_line,
)


def matches(rel_path: str) -> bool:
    return PurePosixPath(rel_path).name == "pyproject.toml"


def _poetry_python_floor(spec: Any) -> str | None:
    if not isinstance(spec, str):
        return None
    text = spec.strip()
    match = re.match(r"^[\^~>=<]*\s*(\d+)(?:\.(\d+))?", text)
    if match:
        return f"{match.group(1)}.{match.group(2) or 0}"
    return floor_python_version(text)


def _poetry_dependency(name: str, value: Any, *, source: str) -> dict[str, Any] | None:
    if isinstance(value, str):
        dep = parse_requirement_line(f"{name}{value}", source=source)
        if dep is None:
            dep = make_dependency(name, specifier=value, raw=f"{name}{value}", source=source)
        return dep
    if isinstance(value, dict):
        version = value.get("version", "")
        markers = value.get("markers")
        spec = version if isinstance(version, str) else ""
        dep = parse_requirement_line(f"{name}{spec}", source=source)
        if dep is None:
            dep = make_dependency(name, specifier=spec, raw=f"{name}{spec}", source=source)
        if markers:
            dep["markers"] = str(markers)
        return dep
    if isinstance(value, list) and value:
        return _poetry_dependency(name, value[0], source=source)
    return None


def _toml_load(rel_path: str, text: str, ctx: ExtractContext) -> tuple[dict[str, Any] | None, EvidenceItem | None]:
    try:
        return tomllib.loads(text), None
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        return None, inference_warning(
            rel_path, f"pyproject.toml could not be parsed: {exc}", commit_sha=ctx.commit_sha
        )


def extract(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    data, error = _toml_load(rel_path, text, ctx)
    if error is not None:
        return [error]
    assert data is not None
    project = as_mapping(data.get("project"))
    tool = as_mapping(data.get("tool"))
    poetry = as_mapping(tool.get("poetry"))
    build_system = as_mapping(data.get("build-system"))

    deps: list[dict[str, Any]] = []
    warnings: list[str] = []
    extras: dict[str, list[dict[str, Any]]] = {}
    classifiers: list[str] = []
    python_requires_raw: Any = None

    if project:
        python_requires_raw = project.get("requires-python")
        for entry in project.get("dependencies") or []:
            if not isinstance(entry, str):
                continue
            dep = parse_requirement_line(entry, source="pyproject")
            if dep is None:
                warnings.append(f"unparseable [project] dependency: {entry[:80]}")
            else:
                deps.append(dep)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group, entries in optional.items():
                parsed = [
                    d
                    for d in (
                        parse_requirement_line(entry, source="pyproject")
                        for entry in entries or []
                        if isinstance(entry, str)
                    )
                    if d is not None
                ]
                if parsed:
                    extras[group] = parsed
        classifiers = [c for c in project.get("classifiers") or [] if isinstance(c, str)]

    poetry_deps = as_mapping(poetry.get("dependencies"))
    if poetry_deps:
        for name, value in poetry_deps.items():
            if name.lower() == "python":
                if python_requires_raw is None:
                    python_requires_raw = (
                        value if isinstance(value, str) else value.get("version") if isinstance(value, dict) else None
                    )
                continue
            dep = _poetry_dependency(name, value, source="pyproject")
            if dep is not None:
                deps.append(dep)
    for group_name in ("dev-dependencies",):
        group = as_mapping(poetry.get(group_name))
        for name, value in group.items():
            dep = _poetry_dependency(name, value, source="pyproject")
            if dep is not None:
                deps.append(dep)
    groups = as_mapping(poetry.get("group"))
    for group in groups.values():
        if not isinstance(group, dict):
            continue
        group_deps = as_mapping(group.get("dependencies"))
        for name, value in group_deps.items():
            dep = _poetry_dependency(name, value, source="pyproject")
            if dep is not None:
                deps.append(dep)

    dependency_groups = data.get("dependency-groups")
    if isinstance(dependency_groups, dict):
        for group, entries in dependency_groups.items():
            parsed = [
                d
                for d in (
                    parse_requirement_line(entry, source="pyproject")
                    for entry in entries or []
                    if isinstance(entry, str)
                )
                if d is not None
            ]
            if parsed:
                extras[group] = parsed

    facts: dict[str, Any] = {}
    if python_requires_raw is not None:
        facts["python_requires_raw"] = str(python_requires_raw)
        floor = _poetry_python_floor(python_requires_raw)
        if floor:
            facts["python_requires"] = floor
    if deps:
        facts["dependencies"] = deps
    if extras:
        facts["extras_require"] = extras
    if classifiers:
        facts["classifiers"] = classifiers
        python_classifiers = classifiers_to_python_versions(classifiers)
        if python_classifiers:
            facts["python_classifiers"] = python_classifiers
    requires = build_system.get("requires")
    if isinstance(requires, list):
        facts["build_requires"] = [r for r in requires if isinstance(r, str)]
    backend = build_system.get("build-backend")
    if isinstance(backend, str):
        facts["build_backend"] = backend

    items: list[EvidenceItem] = []
    if facts:
        items.append(
            EvidenceItem(
                source_kind="manifest_file",
                reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
                facts=facts,
            )
        )
    items.extend(inference_warning(rel_path, warning, commit_sha=ctx.commit_sha) for warning in warnings)
    return items
