"""Self-proof tests for tools/check_global_rules.py (T-INIT-03).

A gate is only trustworthy if a deliberate violation turns it red, so each test
plants exactly one breach in a throwaway tree and asserts the rule fires. The
final test asserts the real repository is clean.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "tools" / "check_global_rules.py"

CLEAN_LIMITS = "MAX_ITERATIONS = 5\nMAX_FILES = 10\nMAX_LINES = 300\n"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_global_rules", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves cls.__module__ via sys.modules
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def seed_tree(root: Path, limits_source: str = CLEAN_LIMITS) -> Path:
    """Create the minimum tree the checker needs, and return the limits path."""

    limits = root / checker.LIMITS_MODULE
    limits.parent.mkdir(parents=True, exist_ok=True)
    limits.write_text(limits_source, encoding="utf-8")
    (limits.parent / "__init__.py").write_text("", encoding="utf-8")
    return limits


def rules_of(violations) -> set[str]:
    return {violation.rule for violation in violations}


def test_clean_tree_passes(tmp_path: Path) -> None:
    seed_tree(tmp_path)
    assert checker.scan(tmp_path) == []


def test_planted_secret_turns_the_gate_red(tmp_path: Path) -> None:
    seed_tree(tmp_path)
    secret = "sk-" + "abcdef123456"  # built at runtime: no literal in this file
    source = tmp_path / "cli" / "src" / "revive_cli" / "__init__.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f'API_KEY="{secret}"\n', encoding="utf-8")

    violations = checker.scan(tmp_path)
    assert "SECRET-ASSIGNMENT" in rules_of(violations)
    reported = " ".join(violation.message for violation in violations)
    assert secret not in reported, "the gate must redact the value it reports"
    assert "sk-a***56" in reported


def test_high_entropy_provider_key_pattern_is_detected(tmp_path: Path) -> None:
    seed_tree(tmp_path)
    token = "ghp_" + "A" * 36
    (tmp_path / "notes.md").write_text(f"token: {token}\n", encoding="utf-8")
    assert "SECRET-GITHUB" in rules_of(checker.scan(tmp_path))


def test_empty_placeholders_are_allowed(tmp_path: Path) -> None:
    seed_tree(tmp_path)
    (tmp_path / ".env.example").write_text(
        "REVIVE_LLM__API_KEY=\nS3_SECRET_KEY=\nS3_ACCESS_KEY=revive\n",
        encoding="utf-8",
    )
    assert checker.scan(tmp_path) == []


def test_task_spec_example_is_allowed_but_real_source_is_not(tmp_path: Path) -> None:
    seed_tree(tmp_path)
    sample = "sk-" + "abcdef123456"
    doc = tmp_path / "docs" / "tasks" / "01-x.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(f'plant `API_KEY="{sample}"` then expect red\n', encoding="utf-8")
    assert checker.scan(tmp_path) == []

    source = tmp_path / "cli" / "src" / "revive_cli" / "__init__.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f'API_KEY="{sample}"\n', encoding="utf-8")
    assert "SECRET-ASSIGNMENT" in rules_of(checker.scan(tmp_path))


def test_lowered_ceiling_is_a_tamper(tmp_path: Path) -> None:
    seed_tree(tmp_path, "MAX_ITERATIONS = 4\nMAX_FILES = 10\nMAX_LINES = 300\n")
    assert "REPAIR-LIMIT-TAMPERED" in rules_of(checker.scan(tmp_path))


def test_raised_ceiling_exceeds_the_global_policy(tmp_path: Path) -> None:
    seed_tree(tmp_path, "MAX_ITERATIONS = 6\nMAX_FILES = 10\nMAX_LINES = 300\n")
    assert "REPAIR-PERMISSION-EXCEEDS" in rules_of(checker.scan(tmp_path))


def test_lowered_ceiling_is_also_a_tamper(tmp_path: Path) -> None:
    seed_tree(tmp_path, "MAX_ITERATIONS = 5\nMAX_FILES = 10\nMAX_LINES = 299\n")
    assert "REPAIR-LIMIT-TAMPERED" in rules_of(checker.scan(tmp_path))


def test_missing_permission_constant_is_detected(tmp_path: Path) -> None:
    seed_tree(tmp_path, "MAX_ITERATIONS = 5\nMAX_FILES = 10\n")
    assert "REPAIR-PERMISSION-MISSING" in rules_of(checker.scan(tmp_path))


def test_missing_limits_module_is_detected(tmp_path: Path) -> None:
    assert "REPAIR-PERMISSION-MISSING" in rules_of(checker.scan(tmp_path))


def test_over_broad_redefinition_elsewhere_is_detected(tmp_path: Path) -> None:
    seed_tree(tmp_path)
    grants = tmp_path / "agents" / "src" / "revive_agents" / "grants.py"
    grants.write_text("MAX_FILES = 99\n", encoding="utf-8")
    violations = checker.scan(tmp_path)
    assert "REPAIR-PERMISSION-EXCEEDS" in rules_of(violations)


def test_excluded_directories_are_not_scanned(tmp_path: Path) -> None:
    seed_tree(tmp_path)
    leaked = "sk-" + "A" * 24
    for ignored in (".venv", "node_modules", "pytest-cache-files-abc123"):
        target = tmp_path / ignored / "leak.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f'API_KEY = "{leaked}"\n', encoding="utf-8")
    assert checker.scan(tmp_path) == []


def test_command_exit_codes(tmp_path: Path) -> None:
    clean = tmp_path / "clean"
    seed_tree(clean)
    assert checker.main([str(clean), "--quiet"]) == 0

    dirty = tmp_path / "dirty"
    seed_tree(dirty, "MAX_ITERATIONS = 42\nMAX_FILES = 10\nMAX_LINES = 300\n")
    assert checker.main([str(dirty), "--quiet"]) == 1

    assert checker.main([str(tmp_path / "missing")]) == 2


def test_repository_is_clean() -> None:
    violations = checker.scan(REPO_ROOT)
    assert violations == [], "\n".join(violation.format() for violation in violations)


@pytest.mark.parametrize("rule", sorted(checker.REPAIR_LIMIT_CEILINGS))
def test_global_ceilings_match_the_overview_doc(rule: str) -> None:
    policy, ceiling = checker.REPAIR_LIMIT_CEILINGS[rule]
    overview = (REPO_ROOT / "docs" / "tasks" / "00-总览与派发指南.md").read_text(encoding="utf-8")
    assert f"{policy}={ceiling}" in overview
