"""Schema loading and validation for the frozen contracts in schemas/.

Every module that emits a contracted document (manifest, score, fingerprint,
job event) validates through here, so the schemas/ directory stays the single
source of truth and no hand-written JSON shape can drift.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import jsonschema

SCHEMA_FILES: dict[str, str] = {
    "manifest": "revive-manifest.schema.json",
    "genome": "environment-genome.schema.json",
    "job-event": "job-event.schema.json",
    "score": "resurrection-score.schema.json",
    "fingerprint": "behavior-fingerprint.schema.json",
}


class SchemaError(RuntimeError):
    """A document does not satisfy its frozen contract."""


class SchemaNotFoundError(SchemaError):
    pass


def schemas_dir() -> Path:
    """Locate the repository schemas/ directory."""

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "schemas"
        if candidate.is_dir():
            return candidate
    raise SchemaNotFoundError("could not locate the schemas/ directory from revive_core")


@lru_cache(maxsize=32)
def load_schema(name: str) -> dict[str, Any]:
    if name not in SCHEMA_FILES:
        raise SchemaNotFoundError(f"unknown schema {name!r}; known: {sorted(SCHEMA_FILES)}")
    path = schemas_dir() / SCHEMA_FILES[name]
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=32)
def _validator(name: str) -> Any:
    schema = load_schema(name)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls(schema)


def validate(instance: Any, name: str) -> None:
    """Validate instance against the named schema; raise SchemaError otherwise."""

    errors = sorted(_validator(name).iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise SchemaError(f"{SCHEMA_FILES[name]} validation failed: {detail}")


def is_valid(instance: Any, name: str) -> bool:
    try:
        validate(instance, name)
        return True
    except SchemaError:
        return False


__all__ = [
    "SCHEMA_FILES",
    "SchemaError",
    "SchemaNotFoundError",
    "schemas_dir",
    "load_schema",
    "validate",
    "is_valid",
]
