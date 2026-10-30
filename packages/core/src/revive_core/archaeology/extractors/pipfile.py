"""Extract evidence from a Pipfile (TOML)."""

from __future__ import annotations

import tomllib
from pathlib import PurePosixPath
from typing import Any

from ..evidence import EvidenceItem, EvidenceReference, ExtractContext, inference_warning
from .common import as_mapping, floor_python_version, make_dependency, parse_requirement_line


def matches(rel_path: str) -> bool:
    return PurePosixPath(rel_path).name == "Pipfile"


def _entry(name: str, value: object, *, source: str) -> dict[str, Any] | None:
    if isinstance(value, str):
        text = value.strip()
        if text in ("", "*"):
            return make_dependency(name, raw=name, source=source)
        dep = parse_requirement_line(f"{name}{text}", source=source)
        if dep is None:
            return make_dependency(name, specifier=text, raw=f"{name}{text}", source=source)
        return dep
    if isinstance(value, dict):
        version = value.get("version", "")
        spec = version if isinstance(version, str) else ""
        dep = parse_requirement_line(f"{name}{spec}", source=source)
        if dep is None:
            dep = make_dependency(name, specifier=spec, raw=f"{name}{spec}", source=source)
        markers = value.get("markers")
        if markers:
            dep["markers"] = str(markers)
        return dep
    return None


def extract(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        return [inference_warning(rel_path, f"Pipfile could not be parsed: {exc}", commit_sha=ctx.commit_sha)]

    deps: list[dict[str, Any]] = []
    for section in ("packages", "dev-packages"):
        group = as_mapping(data.get(section))
        for name, value in group.items():
            dep = _entry(name, value, source="Pipfile")
            if dep is not None:
                deps.append(dep)

    facts: dict[str, Any] = {}
    if deps:
        facts["dependencies"] = deps
    requires = as_mapping(data.get("requires"))
    python_raw = requires.get("python_full_version") or requires.get("python_version")
    if python_raw:
        facts["python_requires_raw"] = str(python_raw)
        floor = floor_python_version(str(python_raw))
        if floor:
            facts["python_requires"] = floor
    if data.get("source"):
        facts["indexes"] = data["source"]

    if not facts:
        return []
    return [
        EvidenceItem(
            source_kind="manifest_file",
            reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
            facts=facts,
        )
    ]
