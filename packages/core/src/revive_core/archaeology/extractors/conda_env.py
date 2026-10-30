"""Extract evidence from conda environment.yml."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

import yaml

from ..evidence import EvidenceItem, EvidenceReference, ExtractContext, inference_warning
from .common import floor_python_version, make_dependency, parse_requirement_line

SPEC_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*(?:[=<>!~]+\s*|\s+)(\S+)$")
_NAMES = {"environment.yml", "environment.yaml", "conda.yml", "conda.yaml"}


def matches(rel_path: str) -> bool:
    return PurePosixPath(rel_path).name.lower() in _NAMES


def _conda_dep(entry: str, *, source: str) -> dict[str, Any] | None:
    text = entry.strip()
    if not text:
        return None
    match = SPEC_RE.match(text)
    if match:
        name, version = match.group(1), match.group(2)
        return make_dependency(name, version=version, specifier=f"=={version}", raw=text, source=source)
    dep = parse_requirement_line(text, source=source)
    if dep is not None:
        return dep
    return make_dependency(text, raw=text, source=source)


def extract(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [inference_warning(rel_path, f"environment.yml could not be parsed: {exc}", commit_sha=ctx.commit_sha)]
    if not isinstance(data, dict):
        return [inference_warning(rel_path, "environment.yml is not a mapping", commit_sha=ctx.commit_sha)]

    deps: list[dict[str, Any]] = []
    warnings: list[str] = []
    for entry in data.get("dependencies") or []:
        if isinstance(entry, str):
            dep = _conda_dep(entry, source="conda")
            if dep is not None:
                deps.append(dep)
        elif isinstance(entry, dict):
            pip_entries = entry.get("pip")
            if isinstance(pip_entries, list):
                for pip_entry in pip_entries:
                    if not isinstance(pip_entry, str):
                        continue
                    parsed = parse_requirement_line(pip_entry, source="conda-pip")
                    if parsed is None:
                        warnings.append(f"unparseable pip entry: {pip_entry[:80]}")
                    else:
                        deps.append(parsed)

    facts: dict[str, Any] = {}
    if deps:
        facts["dependencies"] = deps
    for dep in deps:
        if dep["name"] == "python" and dep["version"]:
            facts["python_requires_raw"] = dep["version"]
            floor = floor_python_version(dep["version"].replace("=", ""))
            if floor:
                facts["python_requires"] = floor
            break
    channels = data.get("channels")
    if isinstance(channels, list):
        facts["channels"] = [c for c in channels if isinstance(c, str)]
    name = data.get("name")
    if isinstance(name, str):
        facts["conda_env_name"] = name

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
