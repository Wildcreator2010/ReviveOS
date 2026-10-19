"""Extract Python-version intent from CI configuration."""

from __future__ import annotations

import configparser
import re
from pathlib import PurePosixPath

import yaml

from ..evidence import EvidenceItem, EvidenceReference, ExtractContext, inference_warning
from .common import normalize_python_version, sort_python_versions

_VERSION_RE = re.compile(r"(\d)\.(\d{1,2})")
# GitHub expression syntax, assembled to avoid template interpolation confusion.
_EXPRESSION_MARKER = "$" + "{{"


def matches(rel_path: str) -> bool:
    posix = rel_path.replace("\\", "/")
    name = PurePosixPath(posix).name.lower()
    if name in ("tox.ini", ".travis.yml", ".travis.yaml"):
        return True
    parts = [p.lower() for p in posix.split("/")]
    return ".github" in parts and "workflows" in parts and name.endswith((".yml", ".yaml"))


def _versions_in_text(text: str) -> list[str]:
    return [f"{m.group(1)}.{int(m.group(2))}" for m in _VERSION_RE.finditer(text)]


def _flatten_versions(value: object) -> list[str]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float, str)):
        text = str(value)
        if _EXPRESSION_MARKER in text:
            return []
        normalized = normalize_python_version(value)
        return [normalized] if normalized else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_versions(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_flatten_versions(item))
        return out
    return []


def _collect_keys(obj: object, keys: set[str], out: list[str]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key.lower().replace("_", "-") in keys:
                out.extend(_flatten_versions(value))
            _collect_keys(value, keys, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, keys, out)


def _raw_scan(text: str, key: str = "python-version") -> list[str]:
    """Recover versions lost to YAML float folding (3.10 becoming 3.1)."""

    out: list[str] = []
    lines = text.splitlines()
    pattern = re.compile(rf"^\s*-?\s*{key}\s*:\s*(.*)$", re.IGNORECASE)
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        rest = match.group(1).strip()
        out.extend(_versions_in_text(rest))
        if rest in ("", "|", ">", "|-", ">-"):
            indent = len(line) - len(line.lstrip())
            for nxt in lines[index + 1 : index + 15]:
                if not nxt.strip():
                    continue
                stripped = nxt.lstrip()
                new_indent = len(nxt) - len(stripped)
                if new_indent <= indent and not stripped.startswith("-"):
                    break
                if stripped.startswith("-"):
                    out.extend(_versions_in_text(nxt))
    return out


def _extract_workflow(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    values: list[str] = []
    warning = None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        data = None
        warning = f"workflow YAML could not be parsed: {exc}"
    if isinstance(data, dict):
        _collect_keys(data, {"python-version", "python_version"}, values)
    values.extend(_raw_scan(text, "python-version"))
    versions = sort_python_versions(values)
    items: list[EvidenceItem] = []
    if versions:
        items.append(
            EvidenceItem(
                source_kind="ci_config",
                reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
                facts={"python_versions": versions, "ci_system": "github-actions"},
            )
        )
    if warning:
        items.append(inference_warning(rel_path, warning, commit_sha=ctx.commit_sha))
    return items


def _extract_travis(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    values: list[str] = []
    warning = None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        data = None
        warning = f".travis.yml could not be parsed: {exc}"
    if isinstance(data, dict) and "python" in data:
        values.extend(_flatten_versions(data["python"]))
    values.extend(_raw_scan(text, "python"))
    versions = sort_python_versions(values)
    items: list[EvidenceItem] = []
    if versions:
        items.append(
            EvidenceItem(
                source_kind="ci_config",
                reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
                facts={"python_versions": versions, "ci_system": "travis"},
            )
        )
    if warning:
        items.append(inference_warning(rel_path, warning, commit_sha=ctx.commit_sha))
    return items


def _extract_tox(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        return [inference_warning(rel_path, f"tox.ini could not be parsed: {exc}", commit_sha=ctx.commit_sha)]
    envlist: list[str] = []
    if parser.has_section("tox"):
        envlist = [f for f in re.split(r"[,\s]+", parser.get("tox", "envlist", fallback="")) if f]
    values: list[str] = []
    for factor in envlist:
        match = re.match(r"py(\d)(\d{1,2})", factor)
        if match:
            values.append(f"{match.group(1)}.{match.group(2)}")
    for section in parser.sections():
        if section.startswith("testenv"):
            basepython = parser.get(section, "basepython", fallback="")
            normalized = normalize_python_version(basepython)
            if normalized:
                values.append(normalized)
    versions = sort_python_versions(values)
    facts: dict = {"envlist": envlist, "ci_system": "tox"}
    if versions:
        facts["python_versions"] = versions
    if not envlist and not versions:
        return []
    return [
        EvidenceItem(
            source_kind="ci_config",
            reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
            facts=facts,
        )
    ]


def extract(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    name = PurePosixPath(rel_path.replace("\\", "/")).name.lower()
    if name == "tox.ini":
        return _extract_tox(rel_path, text, ctx)
    if name in (".travis.yml", ".travis.yaml"):
        return _extract_travis(rel_path, text, ctx)
    return _extract_workflow(rel_path, text, ctx)
