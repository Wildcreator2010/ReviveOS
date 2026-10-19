"""Minimal unified-diff applier used by the in-process execution ports.

The agents package owns the LLM-facing diff parser (revive_agents.diffutil)
for limits and AST reconstruction.  Core cannot import agents (dependency
direction is core <- agents), and the sandbox must be able to apply a diff even
when git is unavailable, so this module re-implements the small, well-specified
subset that sandbox patch application needs.  When git IS available the ports
prefer git apply --check / git apply, and this module is only the fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_DIFF_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffApplyError(ValueError):
    """The diff is malformed or does not apply to the current content."""


@dataclass
class Hunk:
    old_start: int
    lines: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


def _clean(path: str | None) -> str | None:
    if path is None:
        return None
    value = path.strip()
    if value == "/dev/null":
        return None
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return value.replace("\\", "/")


def parse_diff(text: str) -> list[FilePatch]:
    if not text or not text.strip():
        raise DiffApplyError("diff is empty")
    patches: list[FilePatch] = []
    current: FilePatch | None = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            match = _DIFF_HEADER.match(line)
            current = FilePatch(
                old_path=_clean(match.group(1)) if match else None,
                new_path=_clean(match.group(2)) if match else None,
            )
            patches.append(current)
        elif line.startswith("--- "):
            if current is None:
                current = FilePatch(None, None)
                patches.append(current)
            current.old_path = _clean(line[4:].split("\t")[0])
        elif line.startswith("+++ "):
            if current is None:
                current = FilePatch(None, None)
                patches.append(current)
            current.new_path = _clean(line[4:].split("\t")[0])
        elif line.startswith("@@"):
            if current is None:
                raise DiffApplyError("hunk header before any file header")
            match = _HUNK_HEADER.match(line)
            if not match:
                raise DiffApplyError(f"malformed hunk header: {line!r}")
            current.hunks.append(Hunk(old_start=int(match.group(1))))
        elif line.startswith(("+", "-", " ", "\\")):
            if current is None or not current.hunks:
                raise DiffApplyError("diff content before any hunk header")
            if line.startswith("\\"):
                continue
            current.hunks[-1].lines.append((line[0], line[1:]))
        elif line.strip() == "":
            continue
        else:
            raise DiffApplyError(f"unexpected line in diff: {line!r}")
    if not patches:
        raise DiffApplyError("diff contains no file patches")
    return patches


def apply_to_text(original: str, patch: FilePatch) -> str:
    source = original.splitlines()
    out: list[str] = []
    cursor = 0
    for hunk in patch.hunks:
        start = max(hunk.old_start - 1, 0)
        while cursor < start:
            if cursor >= len(source):
                raise DiffApplyError(f"hunk starts past end of {patch.path!r}")
            out.append(source[cursor])
            cursor += 1
        for tag, text in hunk.lines:
            if tag == " ":
                if cursor >= len(source) or source[cursor] != text:
                    raise DiffApplyError(f"context mismatch in {patch.path!r}")
                out.append(source[cursor])
                cursor += 1
            elif tag == "-":
                if cursor >= len(source) or source[cursor] != text:
                    raise DiffApplyError(f"removal mismatch in {patch.path!r}")
                cursor += 1
            elif tag == "+":
                out.append(text)
    while cursor < len(source):
        out.append(source[cursor])
        cursor += 1
    return "\n".join(out) + ("\n" if original.endswith("\n") or out else "")


def apply_to_mapping(files: dict[str, str], diff: str) -> list[str]:
    """Apply a diff to an in-memory {path: text} mapping; return touched paths."""

    touched: list[str] = []
    for patch in parse_diff(diff):
        path = patch.path
        if not path:
            raise DiffApplyError("file patch has no path")
        if not patch.hunks:
            raise DiffApplyError(f"file {path!r} has no hunks")
        original = files.get(path)
        if original is None:
            raise DiffApplyError(f"patch targets missing file {path!r}")
        files[path] = apply_to_text(original, patch)
        touched.append(path)
    return touched


def apply_to_root(root: str | Path, diff: str) -> list[str]:
    """Apply a diff to real files beneath root; return touched paths."""

    base = Path(root)
    files: dict[str, str] = {}
    for patch in parse_diff(diff):
        path = patch.path
        if not path:
            raise DiffApplyError("file patch has no path")
        target = base / path
        if not target.is_file():
            raise DiffApplyError(f"patch targets missing file {path!r}")
        files[path] = target.read_text(encoding="utf-8", errors="replace")
    touched = apply_to_mapping(files, diff)
    for path in touched:
        (base / path).write_text(files[path], encoding="utf-8")
    return touched


__all__ = [
    "DiffApplyError",
    "Hunk",
    "FilePatch",
    "parse_diff",
    "apply_to_text",
    "apply_to_mapping",
    "apply_to_root",
]
