"""Extract pinned dependency sets from lock files (lowest-ambiguity source)."""

from __future__ import annotations

import json
import tomllib
from pathlib import PurePosixPath
from typing import Any

from ..evidence import EvidenceItem, EvidenceReference, ExtractContext, inference_warning
from .common import make_dependency, parse_requirement_line

_LOCK_NAMES = {
    "poetry.lock",
    "pipfile.lock",
    "uv.lock",
    "requirements.lock",
    "requirements-dev.lock",
}


def matches(rel_path: str) -> bool:
    name = PurePosixPath(rel_path).name.lower()
    if name in _LOCK_NAMES:
        return True
    return name.startswith("requirements") and name.endswith(".lock")


def _from_toml(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        return [inference_warning(rel_path, f"lock file could not be parsed: {exc}", commit_sha=ctx.commit_sha)]
    deps: list[dict[str, Any]] = []
    packages = data.get("package")
    if isinstance(packages, list):
        for package in packages:
            if not isinstance(package, dict):
                continue
            name, version = package.get("name"), package.get("version")
            if isinstance(name, str) and isinstance(version, str):
                deps.append(
                    make_dependency(
                        name,
                        version=version,
                        specifier=f"=={version}",
                        raw=f"{name}=={version}",
                        source="lock",
                    )
                )
    if not deps:
        return []
    return [
        EvidenceItem(
            source_kind="manifest_file",
            reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
            facts={"dependencies": deps, "lock": True},
        )
    ]


def _from_json(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [inference_warning(rel_path, f"lock file could not be parsed: {exc}", commit_sha=ctx.commit_sha)]
    deps: list[dict[str, Any]] = []
    for section in ("default", "develop", "packages", "dev-packages"):
        group = data.get(section)
        if not isinstance(group, dict):
            continue
        for name, entry in group.items():
            version = ""
            if isinstance(entry, dict) and isinstance(entry.get("version"), str):
                version = entry["version"].lstrip("=")
            if version:
                deps.append(
                    make_dependency(
                        name,
                        version=version,
                        specifier=f"=={version}",
                        raw=f"{name}=={version}",
                        source="lock",
                    )
                )
    if not deps:
        return []
    return [
        EvidenceItem(
            source_kind="manifest_file",
            reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
            facts={"dependencies": deps, "lock": True},
        )
    ]


def _from_text(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    deps: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        dep = parse_requirement_line(stripped, source="lock")
        if dep is not None:
            deps.append(dep)
    if not deps:
        return []
    return [
        EvidenceItem(
            source_kind="manifest_file",
            reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
            facts={"dependencies": deps, "lock": True},
        )
    ]


def extract(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    name = PurePosixPath(rel_path).name.lower()
    if name.endswith(".json") or name == "pipfile.lock":
        return _from_json(rel_path, text, ctx)
    if name.endswith(".toml") or name in ("uv.lock", "poetry.lock"):
        return _from_toml(rel_path, text, ctx)
    return _from_text(rel_path, text, ctx)
