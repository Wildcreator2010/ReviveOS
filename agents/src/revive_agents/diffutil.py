"""Minimal unified-diff parser and in-memory applier (T-AG-04 helpers).

The repairer uses these helpers to derive touched files and line counts from
the model's diff instead of trusting its self-reported numbers, and to
reconstruct post-patch Python source for 'ast.parse'.  The real apply action
belongs to the sandbox pipeline (T-SB-05); this module never writes to the
target workspace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DIFF_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffError(ValueError):
    """The supplied text is not a well-formed unified diff."""


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    @property
    def is_new(self) -> bool:
        return self.old_path is None and self.new_path is not None

    @property
    def is_delete(self) -> bool:
        return self.new_path is None and self.old_path is not None


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


def parse_unified_diff(text: str) -> list[FilePatch]:
    """Parse a unified diff into FilePatch objects; raise DiffError if invalid."""

    if not text or not text.strip():
        raise DiffError("diff is empty")
    lines = text.splitlines()
    patches: list[FilePatch] = []
    current: FilePatch | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git "):
            match = _DIFF_HEADER.match(line)
            current = FilePatch(old_path=None, new_path=None)
            if match:
                current.old_path = _clean(match.group(1))
                current.new_path = _clean(match.group(2))
            patches.append(current)
        elif line.startswith("--- "):
            if current is None:
                current = FilePatch(old_path=None, new_path=None)
                patches.append(current)
            current.old_path = _clean(line[4:].split("\t")[0].strip())
        elif line.startswith("+++ "):
            if current is None:
                current = FilePatch(old_path=None, new_path=None)
                patches.append(current)
            current.new_path = _clean(line[4:].split("\t")[0].strip())
        elif line.startswith("@@"):
            if current is None:
                raise DiffError("hunk header before any file header")
            match = _HUNK_HEADER.match(line)
            if not match:
                raise DiffError(f"malformed hunk header: {line!r}")
            current.hunks.append(
                Hunk(
                    old_start=int(match.group(1)),
                    old_count=int(match.group(2) or 1),
                    new_start=int(match.group(3)),
                    new_count=int(match.group(4) or 1),
                )
            )
        elif line.startswith(("+", "-", " ", "\\")):
            if current is None or not current.hunks:
                raise DiffError("diff content before any hunk header")
            if line.startswith("\\"):
                index += 1
                continue
            current.hunks[-1].lines.append((line[0], line[1:]))
        elif line.strip() == "":
            pass
        else:
            raise DiffError(f"unexpected line in diff: {line!r}")
        index += 1
    if not patches:
        raise DiffError("diff contains no file patches")
    for patch in patches:
        if not patch.hunks:
            raise DiffError(f"file {patch.path!r} has no hunks")
        if patch.old_path is None and patch.new_path is None:
            raise DiffError("file patch has no path headers")
    return patches


def count_changes(patches: list[FilePatch]) -> tuple[int, int]:
    added = 0
    removed = 0
    for patch in patches:
        for hunk in patch.hunks:
            for tag, _ in hunk.lines:
                if tag == "+":
                    added += 1
                elif tag == "-":
                    removed += 1
    return added, removed


def touched_paths(patches: list[FilePatch]) -> list[str]:
    seen: list[str] = []
    for patch in patches:
        for candidate in (patch.new_path, patch.old_path):
            if candidate and candidate not in seen:
                seen.append(candidate)
    return seen


def _rstrip(value: str) -> str:
    return value.rstrip("\r\n")


def apply_file_patch(original: str, patch: FilePatch) -> str:
    """Apply one file patch to source text in memory; raise DiffError if it cannot apply."""

    source = original.splitlines(keepends=True)
    out: list[str] = []
    cursor = 0
    for hunk in patch.hunks:
        start = max(hunk.old_start - 1, 0)
        while cursor < start:
            if cursor >= len(source):
                raise DiffError(f"hunk starts past end of {patch.path!r}")
            out.append(source[cursor])
            cursor += 1
        for tag, text in hunk.lines:
            if tag == " ":
                if cursor >= len(source) or _rstrip(source[cursor]) != text:
                    raise DiffError(f"context mismatch in {patch.path!r}")
                out.append(source[cursor])
                cursor += 1
            elif tag == "-":
                if cursor >= len(source) or _rstrip(source[cursor]) != text:
                    raise DiffError(f"removal mismatch in {patch.path!r}")
                cursor += 1
            elif tag == "+":
                out.append(text + "\n")
    while cursor < len(source):
        out.append(source[cursor])
        cursor += 1
    return "".join(out)
