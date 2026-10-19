from __future__ import annotations

import inspect

import pytest
from revive_core.errors import ErrorCategory, classify
from revive_core.errors.classifiers import RULES


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.signature)
def test_predicate_accepts_the_arguments_classify_passes(rule):
    """classify() hands each predicate (lowercased text, exit code); arity drift crashed it."""

    assert len(inspect.signature(rule.predicate).parameters) == 2


@pytest.mark.parametrize(
    ("stderr", "exit_code", "expected"),
    [
        ("killed after 300 seconds", 124, "timeout"),
        ("ImportError: cannot import name 'Iterable' from 'collections'", 1, "collections_abc_removed"),
        ("ImportError: cannot import name 'spark' from 'pyspark'", 1, "import_error_cannot_import_name"),
        ("ModuleNotFoundError: No module named 'requests'", 1, "module_not_found"),
        ("ERROR: No matching distribution found for Flask==9.9.9", 1, "no_matching_distribution"),
        ("ERROR: ResolutionImpossible: conflicting dependencies", 1, "pip_resolution_impossible"),
        ("the project requires Python >=3.9", 1, "requires_python_incompatible"),
        ("SyntaxError: Missing parentheses in call to 'print'", 1, "py2_syntax_error"),
        ("ImportError: numpy.core.multiarray failed to import", 1, "numpy_abi_mismatch"),
        ("OSError: libfreetype.so.6: cannot open shared object file", 1, "missing_shared_library"),
        ("/usr/bin/ld: undefined reference to `compute'", 1, "linker_undefined_reference"),
        ("gcc: fatal error: no input files", 1, "compiler_error"),
        ("Segmentation fault (core dumped)", 139, "fallback"),
    ],
)
def test_classify_signatures(stderr, exit_code, expected):
    assert classify("build", stderr, exit_code).signature == expected


def test_classify_returns_enumerated_category_and_stage():
    fact = classify("test", "ModuleNotFoundError: No module named 'yaml'", 1)
    assert isinstance(fact.category, ErrorCategory)
    assert fact.category is ErrorCategory.R02
    assert fact.stage == "test"
    assert fact.raw_excerpt
