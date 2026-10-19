#!/usr/bin/env python3
"""Validate the schemas/ contracts and the tests/contracts fixtures (T-INIT-02 gate).

`schemas/*.json` is the single source of truth for the four cross-stack
contracts. This gate proves two things before pytest ever runs:

1. every schema file is a valid JSON Schema Draft 2020-12 document;
2. every `tests/contracts/fixtures/<name>-valid.json` is accepted by exactly one
   schema and every `<name>-invalid.json` is rejected by exactly one schema.

Usage: `python tools/check_contracts.py [ROOT]`; exit code 0 when clean.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else REPO_ROOT
    schema_dir = root / "schemas"
    fixture_dir = root / "tests" / "contracts" / "fixtures"
    problems: list[str] = []

    schemas: dict[str, dict] = {}
    for path in sorted(schema_dir.glob("*.json")):
        if ".tmp." in path.name:  # transient export, not a versioned contract
            continue
        rel = path.relative_to(root).as_posix()
        try:
            schema = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{rel}: cannot read: {exc}")
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            problems.append(f"{rel}: not a valid Draft 2020-12 schema: {exc.message}")
            continue
        schemas[path.name] = schema

    fixture_count = 0
    if fixture_dir.is_dir():
        fixtures = sorted(fixture_dir.glob("*.json"))
        fixture_count = len(fixtures)
        for fixture in fixtures:
            rel = fixture.relative_to(root).as_posix()
            stem = fixture.stem
            if stem.endswith("-valid"):
                kind, key = "valid", stem[: -len("-valid")]
            elif stem.endswith("-invalid"):
                kind, key = "invalid", stem[: -len("-invalid")]
            else:
                continue  # not a schema fixture
            matches = [name for name in schemas if key in name]
            if len(matches) != 1:
                problems.append(f"{rel}: expected exactly one schema matching {key!r}, found {matches}")
                continue
            try:
                payload = json.loads(fixture.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{rel}: cannot read: {exc}")
                continue
            errors = sorted(
                Draft202012Validator(schemas[matches[0]]).iter_errors(payload),
                key=lambda error: list(error.path),
            )
            if kind == "valid" and errors:
                problems.append(f"{rel}: expected {matches[0]} to accept it, got: {errors[0].message}")
            if kind == "invalid" and not errors:
                problems.append(f"{rel}: expected {matches[0]} to reject it, but it validated")

        covered = {
            name
            for fixture in fixtures
            if (stem := fixture.stem).endswith(("-valid", "-invalid"))
            for name in schemas
            if stem.rsplit("-", 1)[0] in name
        }
        for name in sorted(set(schemas) - covered):
            print(f"[WARN] schemas/{name}: no tests/contracts fixture yet")

    for problem in problems:
        print(f"[FAIL] {problem}")
    if problems:
        print(f"contracts: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"contracts: OK ({len(schemas)} schemas, {fixture_count} fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
