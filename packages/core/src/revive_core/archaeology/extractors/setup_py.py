"""Extract evidence from setup.py (AST only, never eval) and setup.cfg."""

from __future__ import annotations

import ast
import configparser
import re
from pathlib import PurePosixPath

from ..evidence import EvidenceItem, EvidenceReference, ExtractContext, inference_warning
from .common import (
    classifiers_to_python_versions,
    floor_python_version,
    parse_requirement_line,
)

_NAMES = {"setup.py", "setup.cfg"}


def matches(rel_path: str) -> bool:
    return PurePosixPath(rel_path).name in _NAMES


def _literal(node: ast.AST) -> tuple[object, bool]:
    try:
        return ast.literal_eval(node), True
    except (ValueError, SyntaxError):
        return None, False


def _calls_setup(tree: ast.AST) -> ast.Call | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "setup":
                return node
    return None


def _extract_setup_py(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [inference_warning(rel_path, f"setup.py could not be parsed: {exc}", commit_sha=ctx.commit_sha)]
    call = _calls_setup(tree)
    if call is None:
        return []
    facts: dict = {}
    warnings: list[str] = []
    deps: list[dict] = []
    classifiers: list[str] = []
    python_requires_raw: str | None = None

    for keyword in call.keywords:
        if keyword.arg is None:
            continue
        value, ok = _literal(keyword.value)
        if not ok:
            warnings.append(f"setup() argument {keyword.arg} is not a literal and was skipped")
            continue
        if keyword.arg == "python_requires" and isinstance(value, str):
            python_requires_raw = value
        elif keyword.arg == "install_requires" and isinstance(value, (list, tuple)):
            for entry in value:
                if not isinstance(entry, str):
                    continue
                dep = parse_requirement_line(entry, source="setup.py")
                if dep is None:
                    warnings.append(f"unparseable install_requires entry: {entry[:80]}")
                else:
                    deps.append(dep)
        elif keyword.arg == "classifiers" and isinstance(value, (list, tuple)):
            classifiers = [c for c in value if isinstance(c, str)]

    if python_requires_raw is not None:
        facts["python_requires_raw"] = python_requires_raw
        floor = floor_python_version(python_requires_raw)
        if floor:
            facts["python_requires"] = floor
    if deps:
        facts["dependencies"] = deps
    if classifiers:
        facts["classifiers"] = classifiers
        python_classifiers = classifiers_to_python_versions(classifiers)
        if python_classifiers:
            facts["python_classifiers"] = python_classifiers
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


def _multiline(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _extract_setup_cfg(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        return [inference_warning(rel_path, f"setup.cfg could not be parsed: {exc}", commit_sha=ctx.commit_sha)]
    facts: dict = {}
    deps: list[dict] = []
    classifiers: list[str] = []
    warnings: list[str] = []

    if parser.has_section("metadata"):
        classifiers = _multiline(parser.get("metadata", "classifiers", fallback=""))
    python_requires_raw = None
    if parser.has_section("options"):
        python_requires_raw = parser.get("options", "python_requires", fallback=None)
        for entry in _multiline(parser.get("options", "install_requires", fallback="")):
            dep = parse_requirement_line(entry, source="setup.cfg")
            if dep is None:
                warnings.append(f"unparseable install_requires entry: {entry[:80]}")
            else:
                deps.append(dep)
    if python_requires_raw is None and parser.has_section("metadata"):
        python_requires_raw = parser.get("metadata", "requires-python", fallback=None)
    if python_requires_raw:
        facts["python_requires_raw"] = python_requires_raw
        floor = floor_python_version(python_requires_raw)
        if floor:
            facts["python_requires"] = floor
    if deps:
        facts["dependencies"] = deps
    if classifiers:
        facts["classifiers"] = classifiers
        python_classifiers = classifiers_to_python_versions(classifiers)
        if python_classifiers:
            facts["python_classifiers"] = python_classifiers
    if parser.has_section("options.extras_require"):
        extras: dict[str, list[dict]] = {}
        for extra, value in parser.items("options.extras_require"):
            entries = []
            for entry in _multiline(value):
                dep = parse_requirement_line(entry, source="setup.cfg")
                if dep is not None:
                    entries.append(dep)
            if entries:
                extras[extra] = entries
        if extras:
            facts["extras_require"] = extras

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


def extract(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    if PurePosixPath(rel_path).name == "setup.py":
        return _extract_setup_py(rel_path, text, ctx)
    return _extract_setup_cfg(rel_path, text, ctx)


_UNUSED = re  # keep the import meaningful for future regex work
