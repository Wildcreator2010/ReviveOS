"""Evidence items and the filesystem walker that produces them.

EvidenceItem is the raw archaeological record (what a file said and where), while
revive_core.models.genome.Evidence is the trimmed projection that ends up inside
an environment genome. Parsing never raises: a broken file turns into an
inference item carrying a warning note.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger(__name__)

SourceKind = Literal[
    "git_history",
    "manifest_file",
    "ci_config",
    "doc",
    "release_artifact",
    "inference",
]

# Directories that never carry first-party environment declarations.
IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".pnpm-store",
        ".uv-cache",
        ".uv-python",
        "site-packages",
        "dist",
        "build",
    }
)

MAX_FILE_BYTES = 2_000_000


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    line_start: int | None = None
    line_end: int | None = None
    commit_sha: str | None = None
    tag: str | None = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: SourceKind
    reference: EvidenceReference
    facts: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None

    def ref_string(self) -> str:
        """Render the reference as the flat string the genome schema expects."""

        text = self.reference.file
        if self.reference.line_start is not None:
            text += f":{self.reference.line_start}"
        if self.reference.commit_sha:
            text += f"@{self.reference.commit_sha[:12]}"
        return text


@dataclass
class ExtractContext:
    """Carries per-commit context so extractors work on trees and on history."""

    commit_sha: str | None = None
    read_file: Callable[[str], str | None] | None = None


def inference_warning(file: str, note: str, *, commit_sha: str | None = None) -> EvidenceItem:
    return EvidenceItem(
        source_kind="inference",
        reference=EvidenceReference(file=file, commit_sha=commit_sha),
        facts={},
        note=note,
    )


def _is_ignored(rel_path: str) -> bool:
    return any(part in IGNORED_DIRS for part in rel_path.split("/"))


def _safe_read(root: Path, rel_path: str) -> str | None:
    try:
        base = root.resolve()
        raw = root / rel_path
        # A repository must not be able to point evidence reads outside its own tree.
        if raw.is_symlink():
            return None
        candidate = raw.resolve()
        candidate.relative_to(base)
        if candidate.stat().st_size > MAX_FILE_BYTES:
            return None
        return candidate.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def extract_from_text(rel_path: str, text: str, ctx: ExtractContext | None = None) -> list[EvidenceItem]:
    """Dispatch one file's text to every matching extractor."""

    from . import extractors  # local import avoids an import cycle

    return extractors.extract_from_text(rel_path, text, ctx or ExtractContext())


def extract_evidence(
    root: str | Path,
    *,
    commit_sha: str | None = None,
    paths: list[str] | None = None,
    read_file: Callable[[str], str | None] | None = None,
) -> list[EvidenceItem]:
    """Walk root and return evidence for every recognised manifest/CI/doc file."""

    base = Path(root)
    base_resolved = base.resolve()
    ctx = ExtractContext(
        commit_sha=commit_sha,
        read_file=read_file or (lambda rel: _safe_read(base, rel)),
    )
    items: list[EvidenceItem] = []
    candidates = [base / p for p in paths] if paths is not None else sorted(base.rglob("*"))
    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            resolved.relative_to(base_resolved)
        except (OSError, ValueError):  # pragma: no cover - defensive
            continue
        try:
            rel_path = resolved.relative_to(base_resolved).as_posix()
        except ValueError:  # pragma: no cover - already checked above
            continue
        if _is_ignored(rel_path):
            continue
        try:
            if resolved.stat().st_size > MAX_FILE_BYTES:
                continue
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("evidence.read_failed", file=rel_path, error=str(exc))
            items.append(inference_warning(rel_path, f"could not read file: {exc}"))
            continue
        items.extend(extract_from_text(rel_path, text, ctx))
    return items


__all__ = [
    "SourceKind",
    "IGNORED_DIRS",
    "EvidenceReference",
    "EvidenceItem",
    "ExtractContext",
    "inference_warning",
    "extract_from_text",
    "extract_evidence",
]
