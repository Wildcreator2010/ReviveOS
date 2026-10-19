"""Fixed .revive capsule layout (T-CAP-02).

The layout is a constant so the builder, verifier and every consumer agree on
entry names.  Nothing here may change without changing revive-manifest.schema.json
first.
"""

from __future__ import annotations

import re

CAPSULE_FORMAT = "revive/v1"
CAPSULE_SUFFIX = ".revive"

MANIFEST = "manifest.json"
GENOME = "genome.json"
ENVIRONMENT = "environment.json"
DEPENDENCIES_LOCK = "dependencies.lock"
SOURCE_TAR = "source.tar"
PATCHES_DIR = "patches"
SBOM_DIR = "sbom"
SBOM = "sbom/sbom.json"
BEHAVIOR_DIR = "behavior"
FINGERPRINTS = "behavior/fingerprints.json"
TRACES_DIR = "behavior/traces"
TESTS_DIR = "tests"
BEHAVIOR_PLAN = "tests/behavior-plan.json"
DOCKER_DIR = "docker"
DOCKERFILE = "docker/Dockerfile.resurrected"
METADATA_DIR = "metadata"
PROVENANCE = "provenance.json"
METADATA_PROVENANCE = "metadata/provenance.json"
RESURRECTION_REPORT = "metadata/resurrection-report.json"
LLM_TRACES = "metadata/llm-traces.jsonl"
DIGESTS = "digests.json"

#: Entries whose presence the verifier requires.
REQUIRED_ENTRIES: tuple[str, ...] = (
    MANIFEST,
    GENOME,
    ENVIRONMENT,
    DEPENDENCIES_LOCK,
    DOCKERFILE,
    BEHAVIOR_PLAN,
    FINGERPRINTS,
    SBOM,
    PROVENANCE,
    METADATA_PROVENANCE,
    RESURRECTION_REPORT,
    DIGESTS,
)

_SAFE_ENTRY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class CapsuleLayoutError(ValueError):
    """An entry name would escape the capsule or violate the fixed layout."""


def check_entry_name(name: str) -> str:
    """Reject absolute paths, .. escapes and Windows separators."""

    if "\\" in name:
        raise CapsuleLayoutError(f"entry name must use forward slashes: {name!r}")
    if name.startswith("/") or ".." in name.split("/"):
        raise CapsuleLayoutError(f"unsafe capsule entry name: {name!r}")
    if not _SAFE_ENTRY.match(name):
        raise CapsuleLayoutError(f"invalid capsule entry name: {name!r}")
    return name


def patch_name(sequence: int) -> str:
    return f"{PATCHES_DIR}/patch-{sequence:03d}.diff"


def trace_name(index: int) -> str:
    return f"{TRACES_DIR}/case-{index:03d}.json"


__all__ = [
    "CAPSULE_FORMAT",
    "CAPSULE_SUFFIX",
    "MANIFEST",
    "GENOME",
    "ENVIRONMENT",
    "DEPENDENCIES_LOCK",
    "SOURCE_TAR",
    "PATCHES_DIR",
    "SBOM_DIR",
    "SBOM",
    "BEHAVIOR_DIR",
    "FINGERPRINTS",
    "TRACES_DIR",
    "TESTS_DIR",
    "BEHAVIOR_PLAN",
    "DOCKER_DIR",
    "DOCKERFILE",
    "METADATA_DIR",
    "PROVENANCE",
    "METADATA_PROVENANCE",
    "RESURRECTION_REPORT",
    "LLM_TRACES",
    "DIGESTS",
    "REQUIRED_ENTRIES",
    "CapsuleLayoutError",
    "check_entry_name",
    "patch_name",
    "trace_name",
]
