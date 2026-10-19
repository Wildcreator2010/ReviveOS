"""Shared helpers for the manifest/CI extractors."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

PY_MINOR_RE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?:\.\d+)*(?![\d.])")
PY_FACTOR_RE = re.compile(r"(?:^|[_-])py(\d)(\d{1,2})(?:$|[_-])", re.IGNORECASE)


def as_mapping(value: object) -> dict[str, Any]:
    """Return the value as a mapping, or an empty dict when it isn't one."""

    return value if isinstance(value, dict) else {}


def normalize_python_version(value: Any) -> str | None:
    """Return a canonical X.Y string from many shapes, or None if unusable."""

    if value is None or isinstance(value, bool):
        return None
    is_float = isinstance(value, float)
    text = str(value) if isinstance(value, (int, float)) else str(value).strip().strip("'").strip('"')
    if not text:
        return None
    if is_float:
        # YAML folds 3.10 into the float 3.1; a raw-text scan recovers the truth.
        return text
    match = PY_MINOR_RE.search(text)
    if match:
        return f"{int(match.group(1))}.{int(match.group(2))}"
    match = PY_FACTOR_RE.search(text)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return None


def floor_python_version(spec: Any) -> str | None:
    """Lower bound of a PEP 440 python specifier as X.Y (None for upper-only specs)."""

    if spec is None:
        return None
    text = str(spec).strip()
    if not text:
        return None
    try:
        specifiers = SpecifierSet(text)
    except InvalidSpecifier:
        return normalize_python_version(text)
    best: Version | None = None
    for item in specifiers:
        if item.operator not in (">=", ">", "==", "===", "~="):
            continue
        base = item.version.split(".*")[0]
        try:
            parsed = Version(base)
        except InvalidVersion:
            continue
        if best is None or parsed < best:
            best = parsed
    if best is None:
        return normalize_python_version(text)
    return f"{best.major}.{best.minor}"


def sort_python_versions(versions: Iterable[str]) -> list[str]:
    unique: list[str] = []
    for value in versions:
        if value and value not in unique:
            unique.append(value)

    def key(item: str) -> Version:
        try:
            return Version(item)
        except InvalidVersion:  # pragma: no cover - defensive
            return Version("0")

    return sorted(unique, key=key)


def pinned_version(specifier: SpecifierSet) -> str:
    for item in specifier:
        if item.operator in ("==", "===") and not item.version.endswith(".*"):
            return item.version
    return ""


def make_dependency(
    name: str,
    *,
    version: str = "",
    specifier: str = "",
    raw: str = "",
    extras: Iterable[str] | None = None,
    markers: str | None = None,
    source: str = "",
    line: int | None = None,
    pinned: bool | None = None,
) -> dict[str, Any]:
    if pinned is None:
        pinned = bool(version)
    return {
        "name": canonicalize_name(name),
        "version": version,
        "specifier": specifier,
        "raw": raw,
        "extras": sorted(extras or []),
        "markers": markers,
        "source": source,
        "line": line,
        "pinned": bool(pinned),
    }


def dependency_from_requirement(
    req: Requirement, *, raw: str, source: str, line: int | None = None, version: str | None = None
) -> dict[str, Any]:
    if version is None:
        version = pinned_version(req.specifier)
    return make_dependency(
        req.name,
        version=version,
        specifier=str(req.specifier),
        raw=raw,
        extras=sorted(req.extras),
        markers=str(req.marker) if req.marker else None,
        source=source,
        line=line,
    )


def parse_requirement_line(line: str, *, source: str, line_no: int | None = None) -> dict[str, Any] | None:
    raw = line.strip()
    if not raw:
        return None
    try:
        req = Requirement(raw)
    except InvalidRequirement:
        return None
    return dependency_from_requirement(req, raw=raw, source=source, line=line_no)


def classifiers_to_python_versions(classifiers: Iterable[Any] | None) -> list[str]:
    versions: list[str] = []
    for classifier in classifiers or []:
        if not isinstance(classifier, str):
            continue
        normalized = classifier.strip().lower()
        if not normalized.startswith("programming language :: python ::"):
            continue
        tail = classifier.split("::")[-1].strip()
        value = normalize_python_version(tail)
        if value and value not in versions:
            versions.append(value)
    return sort_python_versions(versions)
