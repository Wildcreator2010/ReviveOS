"""Extract weak Python-version hints from README style documents.

These signals are deliberately low priority and are surfaced as inference
evidence by the genome builder.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from ..evidence import EvidenceItem, EvidenceReference, ExtractContext
from .common import sort_python_versions

_NAME_RE = re.compile(r"^readme(\.[a-z0-9]+)?$", re.IGNORECASE)
_PY_RE = re.compile(r"python\s*[:v]?\s*(\d)\.(\d{1,2})", re.IGNORECASE)


def matches(rel_path: str) -> bool:
    return bool(_NAME_RE.match(PurePosixPath(rel_path).name))


def extract(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    versions: list[str] = []
    for match in _PY_RE.finditer(text):
        value = f"{match.group(1)}.{int(match.group(2))}"
        if value not in versions:
            versions.append(value)
    if not versions:
        return []
    return [
        EvidenceItem(
            source_kind="doc",
            reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
            facts={"python_versions": sort_python_versions(versions), "readme_keywords": True},
        )
    ]
