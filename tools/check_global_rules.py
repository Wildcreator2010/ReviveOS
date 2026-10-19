#!/usr/bin/env python3
"""ReviveOS global-rule gate (T-INIT-03).

One machine gate for the non-negotiables of
`docs/tasks/00-总览与派发指南.md` §6:

SECRETS     no hard-coded API key / token / password in source, config
            samples, docs or fixtures (§6.1);
REPAIR      the LLM repair-loop ceilings stay tamper-free:
            max_iterations=5, max_files_changed=10, max_lines_changed=300 (§6.7);
PERMISSION  the agent repair-permission constants exist in the canonical module
            and no module grants more than the global ceilings (§6.7).

A file that legitimately needs secret-shaped test strings opts out with
`check_global_rules: allow-secret-file`; a single line opts out with
`check_global_rules: allow-secret`. Both show up in review on purpose.

Usage::

    python tools/check_global_rules.py [ROOT] [--json] [--quiet]

Exit codes: `0` clean, `1` violations found, `2` usage error.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- canonical global repair policy (docs/tasks/00 §6.7) ---------------------
# Maps the in-code constant to (policy name in the overview doc, global ceiling).
REPAIR_LIMIT_CEILINGS: dict[str, tuple[str, int]] = {
    "MAX_ITERATIONS": ("max_iterations", 5),
    "MAX_FILES": ("max_files_changed", 10),
    "MAX_LINES": ("max_lines_changed", 300),
}

# The one module that must declare the canonical repair ceilings.
LIMITS_MODULE = Path("agents/src/revive_agents/limits.py")

# --- secret catalog ----------------------------------------------------------
# (rule id, regex, human description). The assignment rule captures the literal
# value in group 1 so it can be redacted before it is ever printed.
ASSIGNMENT_RULE = "SECRET-ASSIGNMENT"
SECRET_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("SECRET-OPENAI", r"\bsk-[A-Za-z0-9]{16,}\b", "OpenAI-style API key"),
    ("SECRET-ANTHROPIC", r"\bsk-ant-[A-Za-z0-9_\-]{16,}\b", "Anthropic API key"),
    ("SECRET-GOOGLE", r"\bAIza[0-9A-Za-z_\-]{35}\b", "Google API key"),
    ("SECRET-AWS", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "AWS access key id"),
    ("SECRET-GITHUB", r"\bgh[pousr]_[A-Za-z0-9]{30,}\b", "GitHub token"),
    ("SECRET-SLACK", r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b", "Slack token"),
    ("SECRET-STRIPE", r"\bsk_live_[A-Za-z0-9]{16,}\b", "Stripe live key"),
    (
        "SECRET-PRIVATE-KEY",
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
        "private key block",
    ),
    (
        ASSIGNMENT_RULE,
        r"(?i)\b(?:api[_-]?key|access[_-]?key|secret[_-]?key|client[_-]?secret"
        r"|password|passwd|auth[_-]?token)\b\s*[:=]\s*[\"']([^\"'\n]{12,})[\"']",
        "quoted credential assignment",
    ),
)

# The T-INIT-03 acceptance text quotes this sample verbatim. The exception is
# scoped to the task specs on purpose: the same value inside real source must
# still turn the gate red.
ALLOWED_EXAMPLES: dict[str, frozenset[str]] = {
    "docs/tasks": frozenset({"sk-abcdef123456"}),
}

# Escape hatches for text that must contain a secret-shaped literal (e.g. a
# redaction unit test). Deliberately noisy and reviewable.
ALLOW_PRAGMA = "check_global_rules: allow-secret"
ALLOW_FILE_PRAGMA = "check_global_rules: allow-secret-file"

# --- file discovery ----------------------------------------------------------
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".venv",
        ".uv-cache",
        ".uv-python",
        ".tools",
        ".git",
        ".hg",
        ".svn",
        ".pnpm-store",
        ".pre-commit-cache",
        ".pytest_cache",
        ".pytest-tmp",
        ".pytest-basetemp",
        ".pytest-work",
        ".scratch",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "__pycache__",
        ".next",
        "dist",
        "build",
        "htmlcov",
    }
)
# pytest leaves these behind when the sandbox denies its temp-dir rename; their
# ACLs are unreadable, so any directory walk must prune them.
EXCLUDED_DIR_PREFIXES = ("pytest-cache-files-",)
EXCLUDED_FILE_PREFIXES = (".tmp_",)
EXCLUDED_FILE_NAMES = frozenset({"uv.lock", "poetry.lock", "pnpm-lock.yaml", "package-lock.json", "yarn.lock"})
SCANNED_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".toml",
        ".cfg",
        ".ini",
        ".yaml",
        ".yml",
        ".json",
        ".jsonl",
        ".md",
        ".txt",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".sh",
        ".ps1",
        ".psm1",
        ".bat",
        ".cmd",
        ".sql",
        ".html",
        ".css",
        ".example",
        ".env",
    }
)
SCANNED_FILE_NAMES = frozenset(
    {"Dockerfile", "Makefile", ".npmrc", ".gitignore", ".dockerignore", ".env", ".env.example"}
)

COMPILED_SECRETS = tuple((rule, re.compile(pattern), description) for rule, pattern, description in SECRET_PATTERNS)


@dataclass(frozen=True)
class Violation:
    """One global-rule breach, already safe to print."""

    rule: str
    path: str
    line: int
    message: str

    def format(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"[FAIL] {self.rule} {location}: {self.message}"


def redact(value: str) -> str:
    """Return a fingerprint that identifies a secret without leaking it."""

    text = value.strip()
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}***{text[-2:]}"


def iter_source_files(root: Path):
    """Yield (absolute path, path relative to root) for every scannable file."""

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in EXCLUDED_DIR_NAMES and not name.startswith(EXCLUDED_DIR_PREFIXES)
        )
        for name in sorted(filenames):
            if name in EXCLUDED_FILE_NAMES or name.startswith(EXCLUDED_FILE_PREFIXES):
                continue
            path = Path(dirpath) / name
            if path.suffix.lower() in SCANNED_SUFFIXES or name in SCANNED_FILE_NAMES:
                yield path, path.relative_to(root)


def read_text(path: Path) -> str | None:
    """Read a text file, returning None for unreadable or binary files."""

    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _is_allowed_example(rel_path: str, value: str) -> bool:
    for prefix, values in ALLOWED_EXAMPLES.items():
        if value in values and (rel_path == prefix or rel_path.startswith(prefix + "/")):
            return True
    return False


def scan_secrets(root: Path) -> list[Violation]:
    """Scan every text file for hard-coded credentials."""

    violations: list[Violation] = []
    for path, rel in iter_source_files(root):
        text = read_text(path)
        if text is None or ALLOW_FILE_PRAGMA in text:
            continue
        rel_posix = rel.as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW_PRAGMA in line:
                continue
            for rule, regex, description in COMPILED_SECRETS:
                match = regex.search(line)
                if match is None:
                    continue
                value = match.group(1) if rule == ASSIGNMENT_RULE else match.group(0)
                if _is_allowed_example(rel_posix, value):
                    continue
                violations.append(Violation(rule, rel_posix, lineno, f"{description}: {redact(value)}"))
    return violations


def _int_literal(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        if not isinstance(node.value, bool):
            return node.value
    return None


def _assigned_ints(tree: ast.AST):
    """Yield (name, value, lineno) for integer assignments, annotated or not."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = _int_literal(node.value)
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, value, node.lineno
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = _int_literal(node.value)
            if value is not None:
                yield node.target.id, value, node.lineno


def check_repair_limits(root: Path) -> list[Violation]:
    """Verify the canonical repair ceilings exist and are not tampered with."""

    violations: list[Violation] = []
    limits_path = root / LIMITS_MODULE
    if not limits_path.is_file():
        return [
            Violation(
                "REPAIR-PERMISSION-MISSING",
                LIMITS_MODULE.as_posix(),
                0,
                "canonical repair-limit module is missing; §6.7 ceilings must be declared there",
            )
        ]
    try:
        tree = ast.parse(limits_path.read_text(encoding="utf-8"), filename=str(limits_path))
    except (OSError, SyntaxError) as exc:
        return [
            Violation(
                "REPAIR-PERMISSION-MISSING",
                LIMITS_MODULE.as_posix(),
                0,
                f"cannot parse the repair-limit module: {exc}",
            )
        ]

    declared = {name: (value, lineno) for name, value, lineno in _assigned_ints(tree) if name in REPAIR_LIMIT_CEILINGS}
    for name, (policy, ceiling) in REPAIR_LIMIT_CEILINGS.items():
        if name not in declared:
            violations.append(
                Violation(
                    "REPAIR-PERMISSION-MISSING",
                    LIMITS_MODULE.as_posix(),
                    0,
                    f"permission constant {name} ({policy}) is not declared",
                )
            )
            continue
        value, lineno = declared[name]
        if value > ceiling:
            violations.append(
                Violation(
                    "REPAIR-PERMISSION-EXCEEDS",
                    LIMITS_MODULE.as_posix(),
                    lineno,
                    f"{name}={value} exceeds the global ceiling {policy}={ceiling} (§6.7)",
                )
            )
        elif value != ceiling:
            violations.append(
                Violation(
                    "REPAIR-LIMIT-TAMPERED",
                    LIMITS_MODULE.as_posix(),
                    lineno,
                    f"{name}={value} but §6.7 fixes {policy}={ceiling}; any change is a tamper",
                )
            )
    return violations


def check_foreign_permissions(root: Path) -> list[Violation]:
    """Reject re-declarations of a repair ceiling that grant more than §6.7 allows."""

    violations: list[Violation] = []
    for path, rel in iter_source_files(root):
        if path.suffix != ".py" or rel.as_posix() == LIMITS_MODULE.as_posix():
            continue
        text = read_text(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        for name, value, lineno in _assigned_ints(tree):
            if name not in REPAIR_LIMIT_CEILINGS:
                continue
            policy, ceiling = REPAIR_LIMIT_CEILINGS[name]
            if value > ceiling:
                violations.append(
                    Violation(
                        "REPAIR-PERMISSION-EXCEEDS",
                        rel.as_posix(),
                        lineno,
                        f"{name}={value} re-grants more than the global ceiling {policy}={ceiling}",
                    )
                )
    return violations


def scan(root: Path) -> list[Violation]:
    """Run every rule against a repository root and return sorted violations."""

    root = Path(root).resolve()
    violations = scan_secrets(root)
    violations.extend(check_repair_limits(root))
    violations.extend(check_foreign_permissions(root))
    violations.sort(key=lambda item: (item.path, item.line, item.rule))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ReviveOS global-rule gate (T-INIT-03)")
    parser.add_argument("root", nargs="?", default=str(REPO_ROOT), help="repository root to scan")
    parser.add_argument("--json", action="store_true", help="emit machine-readable findings")
    parser.add_argument("--quiet", action="store_true", help="print nothing when clean")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    violations = scan(root)
    if args.json:
        print(json.dumps([asdict(item) for item in violations], ensure_ascii=False, indent=2))
    elif violations:
        for violation in violations:
            print(violation.format())
        print(
            f"{len(violations)} violation(s) found by tools/check_global_rules.py",
            file=sys.stderr,
        )
    elif not args.quiet:
        print(f"check_global_rules: OK ({root}) - no secrets, repair ceilings intact")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
