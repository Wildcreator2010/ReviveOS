"""Revive capsule building, verification and replay (T-CAP-02/03)."""

from .builder import (
    CapsuleBuildError,
    RunState,
    build_capsule,
    default_capsule_path,
    generate_sbom,
    verify_capsule_structure,
)
from .layout import CAPSULE_FORMAT, CAPSULE_SUFFIX
from .replay import ReplayResult, capsule_manifest, replay
from .verify import (
    EXIT_BEHAVIOR_DRIFT,
    EXIT_CORRUPT,
    EXIT_OK,
    RebuildResult,
    VerifyReport,
    extract_capsule,
    verify,
)

__all__ = [
    "CapsuleBuildError",
    "RunState",
    "build_capsule",
    "default_capsule_path",
    "generate_sbom",
    "verify_capsule_structure",
    "CAPSULE_FORMAT",
    "CAPSULE_SUFFIX",
    "ReplayResult",
    "capsule_manifest",
    "replay",
    "EXIT_BEHAVIOR_DRIFT",
    "EXIT_CORRUPT",
    "EXIT_OK",
    "RebuildResult",
    "VerifyReport",
    "extract_capsule",
    "verify",
]
