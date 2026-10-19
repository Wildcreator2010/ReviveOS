"""Deterministic inference rule table.

This module is the product soul: the priority order below decides every genome.
It is data-only so reports and evidence notes can quote it verbatim.
"""

from __future__ import annotations

RULESET_VERSION = "core-rules-1"

# Python version: python_requires > CI matrix > Dockerfile base tag > classifiers > README keywords.
PYTHON_PRIORITY: tuple[str, ...] = (
    "python_requires",
    "ci_matrix",
    "dockerfile_base",
    "classifiers",
    "readme_keywords",
)

PYTHON_RULE_LABEL: dict[str, str] = {
    "python_requires": "python_requires (setup.py/setup.cfg/pyproject)",
    "ci_matrix": "CI python-version matrix",
    "dockerfile_base": "Dockerfile base image tag",
    "classifiers": "classifiers Programming Language :: Python :: X.Y",
    "readme_keywords": "README keyword (marker: inference)",
}

PYTHON_CONFIDENCE: dict[str, float] = {
    "python_requires": 0.95,
    "ci_matrix": 0.90,
    "dockerfile_base": 0.85,
    "classifiers": 0.80,
    "readme_keywords": 0.40,
}

# Dependency version: lock file > pinned (==) > PyPI latest before last activity > unresolved.
DEPENDENCY_PRIORITY: tuple[str, ...] = ("lock", "pinned", "pypi_timeline", "unpinned")

DEPENDENCY_CONFIDENCE: dict[str, float] = {
    "lock": 0.98,
    "pinned": 0.90,
    "pypi": 0.60,
    "inference": 0.20,
}

DEPENDENCY_SOURCE_LABEL: dict[str, str] = {
    "lock": "lock file",
    "pinned": "pinned (==)",
    "pypi": "PyPI latest before last activity",
    "inference": "unresolved (marker: inference)",
}

CONFLICT_CONFIDENCE_CAP = 0.70

# Overall confidence is the weighted geometric mean of the field confidences.
FIELD_WEIGHTS: dict[str, float] = {
    "python": 0.40,
    "dependencies": 0.35,
    "os": 0.15,
    "cuda": 0.05,
    "system_libs": 0.05,
}

NEGATIVE_CONFIDENCE: dict[str, float] = {
    "python": 0.10,
    "dependencies": 0.20,
    "os": 0.10,
    "cuda": 0.10,
    "system_libs": 0.50,
}


__all__ = [
    "RULESET_VERSION",
    "PYTHON_PRIORITY",
    "PYTHON_RULE_LABEL",
    "PYTHON_CONFIDENCE",
    "DEPENDENCY_PRIORITY",
    "DEPENDENCY_CONFIDENCE",
    "DEPENDENCY_SOURCE_LABEL",
    "CONFLICT_CONFIDENCE_CAP",
    "FIELD_WEIGHTS",
    "NEGATIVE_CONFIDENCE",
]
