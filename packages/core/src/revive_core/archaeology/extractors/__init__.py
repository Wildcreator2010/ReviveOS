"""Manifest/CI evidence extractors.

Every extractor exposes matches(rel_path) -> bool and
extract(rel_path, text, ctx) -> list[EvidenceItem]. Failures are downgraded to an
inference warning item; extraction never aborts the walk.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import structlog

from ..evidence import EvidenceItem, ExtractContext, inference_warning
from . import (
    ci_config,
    conda_env,
    dockerfile,
    lockfile,
    pipfile,
    pyproject,
    readme,
    requirements,
    setup_py,
)

log = structlog.get_logger(__name__)


class Extractor(Protocol):
    def matches(self, rel_path: str) -> bool: ...

    def extract(self, rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]: ...


MODULES: tuple[Extractor, ...] = (
    requirements,
    setup_py,
    pyproject,
    pipfile,
    conda_env,
    dockerfile,
    ci_config,
    readme,
    lockfile,
)

ExtractorFn = Callable[[str, str, ExtractContext], list[EvidenceItem]]


def matching_modules(rel_path: str) -> list[Extractor]:
    return [module for module in MODULES if module.matches(rel_path)]


def extract_from_text(rel_path: str, text: str, ctx: ExtractContext | None = None) -> list[EvidenceItem]:
    context = ctx or ExtractContext()
    items: list[EvidenceItem] = []
    for module in matching_modules(rel_path):
        module_name = getattr(module, "__name__", repr(module))
        try:
            items.extend(module.extract(rel_path, text, context))
        except Exception as exc:  # noqa: BLE001 - parsing must never abort the walk
            log.warning(
                "extractor.failed",
                module=module_name,
                file=rel_path,
                error=f"{type(exc).__name__}: {exc}",
            )
            items.append(
                inference_warning(
                    rel_path,
                    f"{module_name} failed: {type(exc).__name__}: {exc}",
                    commit_sha=context.commit_sha,
                )
            )
    return items


__all__ = [
    "MODULES",
    "Extractor",
    "ExtractorFn",
    "matching_modules",
    "extract_from_text",
    "requirements",
    "setup_py",
    "pyproject",
    "pipfile",
    "conda_env",
    "dockerfile",
    "ci_config",
    "readme",
    "lockfile",
]
