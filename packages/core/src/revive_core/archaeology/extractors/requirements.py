"""Extract evidence from requirements*.txt (including one level of -r includes)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Any

from ..evidence import EvidenceItem, EvidenceReference, ExtractContext, inference_warning
from .common import parse_requirement_line

NAME_RE = re.compile(r"^requirements.*\.txt$", re.IGNORECASE)


def matches(rel_path: str) -> bool:
    return bool(NAME_RE.match(PurePosixPath(rel_path).name))


def _logical_lines(text: str) -> Iterator[tuple[int, str]]:
    buffer = ""
    start: int | None = None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if start is None:
            start = number
        if line.endswith("\\"):
            buffer += line[:-1].strip() + " "
            continue
        buffer += line
        if buffer.strip():
            yield start, buffer
        buffer = ""
        start = None
    if buffer.strip():
        yield start or 1, buffer


def _strip_comment(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("#"):
        return ""
    match = re.search(r"\s#.*$", stripped)
    if match:
        stripped = stripped[: match.start()]
    return stripped.strip()


def _join(rel_path: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return str(PurePosixPath(rel_path).parent / target)


def _extract_file(rel_path: str, text: str, ctx: ExtractContext, *, depth: int) -> list[EvidenceItem]:
    deps: list[dict[str, Any]] = []
    includes: list[str] = []
    options: list[str] = []
    warnings: list[str] = []
    items: list[EvidenceItem] = []

    for line_no, logical in _logical_lines(text):
        content = _strip_comment(logical)
        # Drop pip per-requirement options such as --hash=... before parsing.
        content = re.sub(r"\s--[A-Za-z][A-Za-z0-9_-]*(?:=\S+)?", "", content).strip()
        if not content:
            continue
        lowered = content.lower()
        if lowered.startswith("-r ") or lowered.startswith("--requirement "):
            target = content.split(None, 1)[1].strip()
            includes.append(target)
            child = _join(rel_path, target)
            if depth == 0 and ctx.read_file is not None:
                child_text = ctx.read_file(child)
                if child_text is None:
                    warnings.append(f"included requirements file not found: {child}")
                else:
                    nested = _extract_file(child, child_text, ctx, depth=1)
                    for item in nested:
                        item.note = (f"{item.note}; " if item.note else "") + f"included from {rel_path}"
                    items.extend(nested)
            elif depth > 0:
                warnings.append(f"nested -r ignored (only one level is expanded): {target}")
            continue
        if lowered.startswith(("-e ", "--editable ")) or content.startswith("--"):
            options.append(content)
            continue
        dep = parse_requirement_line(content, source="requirements", line_no=line_no)
        if dep is None:
            warnings.append(f"unparseable requirement line {rel_path}:{line_no}: {content[:80]}")
            continue
        deps.append(dep)

    facts: dict[str, Any] = {}
    if deps:
        facts["dependencies"] = deps
    if includes:
        facts["requirements_includes"] = includes
    if options:
        facts["requirements_options"] = options
    if facts:
        items.insert(
            0,
            EvidenceItem(
                source_kind="manifest_file",
                reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
                facts=facts,
            ),
        )
    items.extend(inference_warning(rel_path, warning, commit_sha=ctx.commit_sha) for warning in warnings)
    return items


def extract(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    return _extract_file(rel_path, text, ctx, depth=0)
