"""Death-cause taxonomy R01-R08 (+ R99 timeout, UNKNOWN fallback).

The codes align with the sandbox failure classes the Repair Agent consumes.
Signatures live in classifiers.py and are treated as a stable contract.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCategory(StrEnum):
    R01 = "R01"  # removed runtime / stdlib API (ImportError, cannot import name)
    R02 = "R02"  # missing or vanished dependency distribution
    R03 = "R03"  # dependency resolution conflict
    R04 = "R04"  # native extension build / link failure
    R05 = "R05"  # missing system shared library
    R06 = "R06"  # python version incompatible (Requires-Python)
    R07 = "R07"  # python 2 syntax/semantics no longer accepted
    R08 = "R08"  # binary ABI break
    R99 = "R99"  # timeout
    UNKNOWN = "UNKNOWN"


CATEGORY_TITLES: dict[ErrorCategory, str] = {
    ErrorCategory.R01: "removed runtime or stdlib API",
    ErrorCategory.R02: "missing or vanished dependency",
    ErrorCategory.R03: "dependency resolution conflict",
    ErrorCategory.R04: "native build or link failure",
    ErrorCategory.R05: "missing system shared library",
    ErrorCategory.R06: "python version incompatible",
    ErrorCategory.R07: "python 2 syntax or semantics",
    ErrorCategory.R08: "binary ABI break",
    ErrorCategory.R99: "timeout",
    ErrorCategory.UNKNOWN: "unclassified",
}


__all__ = ["ErrorCategory", "CATEGORY_TITLES"]
