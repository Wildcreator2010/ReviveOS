"""Classify sandbox stderr into actionable ErrorFacts.

Rules are evaluated in a fixed order with linear substring/regex checks only, so
a 1 MB log is handled in well under 200 ms. Signatures are a public contract:
never rename one, add new rules with new names instead.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from .taxonomy import CATEGORY_TITLES, ErrorCategory

MAX_SCAN_CHARS = 1_000_000
MAX_EXCERPT_CHARS = 4_000
MAX_SUSPECT_FILES = 10


class Stage(StrEnum):
    BUILD = "build"
    RUN = "run"
    TEST = "test"


@dataclass
class ErrorFact:
    category: ErrorCategory
    signature: str
    suspect_files: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    raw_excerpt: str = ""
    stage: str = "build"


Predicate = Callable[[str, int], bool]

_FILE_RE = re.compile(r"[\w./\\-]+\.(?:py|pyx|so|c|cc|cpp|cxx|h|hpp)\b")
_FILE_QUOTED_RE = re.compile(r'File "([^"]+)"')


def _has_any(lower: str, needles: tuple[str, ...]) -> bool:
    return any(needle in lower for needle in needles)


def _timeout(lower: str, exit_code: int) -> bool:
    return exit_code == 124 or _has_any(lower, ("timed out", "timeout", "deadline exceeded"))


def _collections_abc(lower: str, _exit: int) -> bool:
    if "cannot import name" in lower and ("'collections'" in lower or "collections'" in lower):
        return True
    return bool(
        re.search(
            r"from collections import (?:iterable|mapping|mutablemapping|sequence|set|callable|hashable|container|sized)",  # noqa: E501
            lower,
        )
    )


def _cannot_import_name(lower: str, _exit: int) -> bool:
    return "cannot import name" in lower


def _module_not_found(lower: str, _exit: int) -> bool:
    return "modulenotfounderror" in lower or "no module named " in lower


def _no_matching_distribution(lower: str, _exit: int) -> bool:
    return "no matching distribution found" in lower


def _resolution_impossible(lower: str, _exit: int) -> bool:
    return "resolutionimpossible" in lower or "conflicting dependencies" in lower


def _requires_python(lower: str, _exit: int) -> bool:
    return (
        "requires-python" in lower
        or "requires a different python" in lower
        or "ignored the following versions that require a different python" in lower
        or "requires python" in lower
    )


def _py2_syntax(lower: str, _exit: int) -> bool:
    if "missing parentheses in call to 'print'" in lower or 'missing parentheses in call to "print"' in lower:
        return True
    if "syntaxerror" in lower and re.search(r"(?m)^\s*print\s+[^\s(]", lower):
        return True
    if "syntaxerror" in lower and re.search(r"except\s+[^:,\n]+,[^:\n]+:", lower):
        return True
    return False


def _numpy_abi(lower: str, _exit: int) -> bool:
    return (
        "numpy.core.multiarray failed to import" in lower
        or "module compiled against api version" in lower
        or "numpy.dtype size changed" in lower
        or ("numpy" in lower and "abi" in lower)
    )


def _missing_shared_library(lower: str, _exit: int) -> bool:
    return (
        "cannot open shared object file" in lower
        or "error while loading shared libraries" in lower
        or bool(re.search(r"lib[^\s\n]{0,120}\.so(?:\.\d+)*", lower))
    )


def _linker_undefined_reference(lower: str, _exit: int) -> bool:
    return "undefined reference to" in lower or "undefined symbol:" in lower


def _compiler_error(lower: str, _exit: int) -> bool:
    return (
        "error: command '" in lower
        or bool(re.search(r"\b(?:gcc|g\+\+|cc|clang)\b[^\n]{0,120}error", lower))
        or "fatal error:" in lower
    )


@dataclass(frozen=True)
class ErrorRule:
    signature: str
    category: ErrorCategory
    hints: tuple[str, ...]
    predicate: Predicate


RULES: tuple[ErrorRule, ...] = (
    ErrorRule(
        "timeout",
        ErrorCategory.R99,
        (
            "Increase the sandbox timeout or profile which step is slow.",
            "Check for network waits in install steps.",
        ),
        _timeout,
    ),
    ErrorRule(
        "collections_abc_removed",
        ErrorCategory.R01,
        (
            "collections.abc members were removed in Python 3.10.",
            "Import from collections.abc instead of collections.",
        ),
        _collections_abc,
    ),
    ErrorRule(
        "import_error_cannot_import_name",
        ErrorCategory.R01,
        (
            "The imported symbol does not exist in the installed version.",
            "Pin or downgrade the providing package.",
        ),
        _cannot_import_name,
    ),
    ErrorRule(
        "module_not_found",
        ErrorCategory.R02,
        (
            "The dependency is missing from the environment.",
            "Add the dependency or fix the removed index.",
        ),
        _module_not_found,
    ),
    ErrorRule(
        "no_matching_distribution",
        ErrorCategory.R02,
        (
            "No release satisfies the pin on this Python/platform.",
            "Relax or re-resolve the pinned version.",
        ),
        _no_matching_distribution,
    ),
    ErrorRule(
        "pip_resolution_impossible",
        ErrorCategory.R03,
        (
            "Constraints are mutually unsatisfiable.",
            "Relax conflicting pins or use a historical resolver.",
        ),
        _resolution_impossible,
    ),
    ErrorRule(
        "requires_python_incompatible",
        ErrorCategory.R06,
        (
            "The distribution requires a different Python version.",
            "Switch the interpreter or pick a compatible release.",
        ),
        _requires_python,
    ),
    ErrorRule(
        "py2_syntax_error",
        ErrorCategory.R07,
        (
            "Python 2 syntax is invalid on Python 3.",
            "Apply 2to3/print function and except-as fixes.",
        ),
        _py2_syntax,
    ),
    ErrorRule(
        "numpy_abi_mismatch",
        ErrorCategory.R08,
        (
            "Extension was built against a different numpy ABI.",
            "Reinstall the extension against the target numpy.",
        ),
        _numpy_abi,
    ),
    ErrorRule(
        "missing_shared_library",
        ErrorCategory.R05,
        (
            "A system shared library is absent.",
            "Install the matching -dev system package in the image.",
        ),
        _missing_shared_library,
    ),
    ErrorRule(
        "linker_undefined_reference",
        ErrorCategory.R04,
        ("The linker cannot resolve a symbol.", "Add the missing library or compiler flag."),
        _linker_undefined_reference,
    ),
    ErrorRule(
        "compiler_error",
        ErrorCategory.R04,
        (
            "The compiler rejected the source.",
            "Inspect the first compiler error and patch the source.",
        ),
        _compiler_error,
    ),
)

FALLBACK_SIGNATURE = "fallback"


def _normalize_stage(stage: object) -> str:
    if isinstance(stage, Stage):
        return stage.value
    text = str(stage or "build").strip().lower()
    return text if text in {"build", "run", "test"} else "build"


def _suspect_files(text: str) -> list[str]:
    found: list[str] = []
    for match in _FILE_QUOTED_RE.finditer(text):
        candidate = match.group(1).strip()
        if candidate and candidate not in found:
            found.append(candidate)
    for match in _FILE_RE.finditer(text):
        candidate = match.group(0).strip()
        if candidate and candidate not in found:
            found.append(candidate)
    return found[:MAX_SUSPECT_FILES]


def classify(stage: object, stderr: str, exit_code: int) -> ErrorFact:
    """Return the first matching rule, or the UNKNOWN/fallback fact."""

    text = stderr or ""
    scanned = text[:MAX_SCAN_CHARS]
    lower = scanned.lower()
    normalized_stage = _normalize_stage(stage)
    for rule in RULES:
        if rule.predicate(lower, exit_code):
            return ErrorFact(
                category=rule.category,
                signature=rule.signature,
                suspect_files=_suspect_files(scanned),
                hints=list(rule.hints),
                raw_excerpt=scanned[:MAX_EXCERPT_CHARS],
                stage=normalized_stage,
            )
    return ErrorFact(
        category=ErrorCategory.UNKNOWN,
        signature=FALLBACK_SIGNATURE,
        suspect_files=_suspect_files(scanned),
        hints=[f"Unclassified failure ({CATEGORY_TITLES[ErrorCategory.UNKNOWN]}); inspect the raw excerpt."],
        raw_excerpt=scanned[:MAX_EXCERPT_CHARS],
        stage=normalized_stage,
    )


__all__ = ["Stage", "ErrorFact", "ErrorRule", "RULES", "FALLBACK_SIGNATURE", "classify"]
