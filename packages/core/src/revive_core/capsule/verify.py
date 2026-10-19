"""revive verify - capsule reproducibility acceptance (T-CAP-03).

Order is fixed:

    schema validate -> per-file sha256 -> rebuild -> behaviour rematch

Exit codes (documented, used by the CLI):
    0  everything requested passed
    1  behaviour drift (fingerprints no longer match)
    2  structural corruption OR rebuild failure

A structural failure always names the offending entry.  Verify never claims
reproducibility it did not observe: when no rebuild backend is available the
report says so and verified stays false.
"""

from __future__ import annotations

import shutil
import tarfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .builder import verify_capsule_structure
from .layout import CapsuleLayoutError, check_entry_name

EXIT_OK = 0
EXIT_BEHAVIOR_DRIFT = 1
EXIT_CORRUPT = 2


@dataclass
class RebuildResult:
    ok: bool
    behavior_rematch: bool | None = None
    score_reproduced: float | None = None
    backend: str = ""
    error: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


class Rebuilder(Protocol):
    name: str

    async def rebuild(self, capsule_dir: Path) -> RebuildResult: ...


@dataclass
class VerifyReport:
    capsule: str
    manifest_ok: bool
    digests_ok: bool
    docker_rebuild_ok: bool | None
    behavior_rematch: bool | None
    score_reproduced: float | None
    exit_code: int
    verified: bool
    errors: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    bad_entries: list[str] = field(default_factory=list)
    rebuild_backend: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capsule": self.capsule,
            "manifest_ok": self.manifest_ok,
            "digests_ok": self.digests_ok,
            "docker_rebuild_ok": self.docker_rebuild_ok,
            "behavior_rematch": self.behavior_rematch,
            "score_reproduced": self.score_reproduced,
            "exit_code": self.exit_code,
            "verified": self.verified,
            "errors": list(self.errors),
            "missing": list(self.missing),
            "bad_entries": list(self.bad_entries),
            "rebuild_backend": self.rebuild_backend,
        }


def extract_capsule(path: str | Path, destination: str | Path) -> dict[str, Path]:
    """Safely extract every file of a capsule into destination."""

    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    extracted: dict[str, Path] = {}
    with tarfile.open(path, mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            try:
                check_entry_name(member.name)
            except CapsuleLayoutError as exc:
                raise ValueError(f"unsafe capsule entry: {exc}") from exc
            target = dest / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:  # pragma: no cover - defensive
                continue
            target.write_bytes(source.read())
            extracted[member.name] = target
    return extracted


async def verify(
    capsule: str | Path,
    *,
    rebuilder: Rebuilder | None = None,
    score_recompute: Callable[[dict[str, Any]], float | None] | None = None,
) -> VerifyReport:
    """Verify a capsule end to end."""

    structural = verify_capsule_structure(capsule)
    report = VerifyReport(
        capsule=str(capsule),
        manifest_ok=bool(structural.get("manifest_ok")),
        digests_ok=bool(structural.get("digests_ok")),
        docker_rebuild_ok=None,
        behavior_rematch=None,
        score_reproduced=None,
        exit_code=EXIT_OK,
        verified=False,
        errors=list(structural.get("errors", [])),
        missing=list(structural.get("missing", [])),
        bad_entries=list(structural.get("bad_entries", [])),
    )
    if not report.manifest_ok or not report.digests_ok or report.missing:
        report.exit_code = EXIT_CORRUPT
        report.verified = False
        return report

    if rebuilder is None:
        # Structural checks passed but nothing was reproduced: never claim verified.
        report.rebuild_backend = None
        report.exit_code = EXIT_CORRUPT
        report.verified = False
        report.errors.append("rebuild skipped: no rebuild backend available")
        return report

    report.rebuild_backend = getattr(rebuilder, "name", type(rebuilder).__name__)
    from ..sandbox.executor import sandbox_tmpdir

    workdir = sandbox_tmpdir("revive-verify-")
    try:
        extract_capsule(capsule, workdir)
        result: RebuildResult = await rebuilder.rebuild(workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    report.docker_rebuild_ok = result.ok
    report.behavior_rematch = result.behavior_rematch
    report.score_reproduced = result.score_reproduced
    if not result.ok:
        report.exit_code = EXIT_CORRUPT
        report.errors.append(result.error or "rebuild failed")
        report.verified = False
        return report
    if result.behavior_rematch is False:
        report.exit_code = EXIT_BEHAVIOR_DRIFT
        report.verified = False
        return report
    report.verified = result.behavior_rematch is True
    report.exit_code = EXIT_OK
    return report


__all__ = [
    "EXIT_OK",
    "EXIT_BEHAVIOR_DRIFT",
    "EXIT_CORRUPT",
    "RebuildResult",
    "Rebuilder",
    "VerifyReport",
    "extract_capsule",
    "verify",
]
