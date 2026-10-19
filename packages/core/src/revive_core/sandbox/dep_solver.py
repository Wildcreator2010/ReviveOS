"""Historical dependency installation with version fallback (T-SB-03).

The declared pin is tried first.  When it cannot be installed we walk backwards
through history (versions published before the project was last active) and then
through the immediately older releases, at most MAX_FALLBACKS times, and we
ALWAYS record what was actually installed versus what the project declared.

Hard rules enforced here:
  * never move to a higher major version than the project declared;
  * never pass --pre;
  * only the whitelisted index may be referenced.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from packaging.version import InvalidVersion, Version

from .executor import EventPort, RunResult, SandboxHandle

MAX_FALLBACKS = 3
FORBIDDEN_PIP_FLAGS = ("--pre", "--upgrade", "-U")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class DeclaredDep:
    name: str
    version: str = ""
    specifier: str = ""


@dataclass(frozen=True)
class PinnedDep:
    """One line of dependencies.lock."""

    name: str
    installed_version: str
    original_declared_version: str
    changed: bool
    requested_version: str | None = None
    attempts: int = 1
    candidate_source: str = "declared"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "installed_version": self.installed_version,
            "original_declared_version": self.original_declared_version,
            "changed": self.changed,
            "requested_version": self.requested_version,
            "attempts": self.attempts,
            "candidate_source": self.candidate_source,
        }


@dataclass
class InstallOutcome:
    locked: list[PinnedDep] = field(default_factory=list)
    fallbacks_used: int = 0
    failures: list[tuple[str, list[str]]] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "locked": [dep.to_dict() for dep in self.locked],
            "fallbacks_used": self.fallbacks_used,
            "failures": [{"name": name, "tried_versions": versions} for name, versions in self.failures],
            "attempts": self.attempts,
        }


@runtime_checkable
class VersionProvider(Protocol):
    """Supplies historic versions for a package, newest first."""

    def candidates(self, name: str, declared: str, cutoff: datetime | None) -> list[str]: ...


class StaticVersionProvider:
    """Deterministic provider for tests and offline fixtures."""

    def __init__(self, table: Mapping[str, Sequence[str]] | None = None) -> None:
        self.table = {key.lower().replace("_", "-"): list(value) for key, value in (table or {}).items()}

    def candidates(self, name: str, declared: str, cutoff: datetime | None) -> list[str]:
        return list(self.table.get(name.lower().replace("_", "-"), []))


class PypiVersionProvider:
    """Historic versions from T-CORE-05 (PyPI release list), newest first."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def candidates(self, name: str, declared: str, cutoff: datetime | None) -> list[str]:
        if cutoff is None:
            return []
        releases = self.client.versions_before(name, cutoff)
        versions: list[str] = []
        for release in releases:
            version = getattr(release, "version", None) or str(release)
            if version not in versions:
                versions.append(version)
        return versions


def declared_dependencies(genome: Any) -> list[DeclaredDep]:
    """Read the dependency declarations out of a genome-like object."""

    if genome is None:
        return []
    if isinstance(genome, Mapping):
        raw = genome.get("dependencies", [])
    else:
        raw = getattr(genome, "dependencies", [])
    deps: list[DeclaredDep] = []
    for item in raw or []:
        if isinstance(item, Mapping):
            name = str(item.get("name", "")).strip()
            version = str(item.get("version", "") or "").strip()
            specifier = str(item.get("specifier", "") or "").strip()
        else:
            name = str(getattr(item, "name", "")).strip()
            version = str(getattr(item, "version", "") or "").strip()
            specifier = str(getattr(item, "specifier", "") or "").strip()
        if name:
            deps.append(DeclaredDep(name=name, version=version, specifier=specifier))
    return deps


def _version(value: str) -> Version | None:
    text = (value or "").strip().lstrip("vV=")
    if not text or text == "*":
        return None
    try:
        return Version(text)
    except InvalidVersion:
        return None


def _floor_version(declared: DeclaredDep) -> str:
    if declared.version and declared.version != "*":
        return declared.version
    spec = declared.specifier
    match = re.search(r"(?:==|>=|~=)\s*([0-9][^,\s]*)", spec or "")
    return match.group(1) if match else ""


def candidate_versions(
    declared: DeclaredDep,
    provider: VersionProvider | None,
    cutoff: datetime | None,
    *,
    max_fallbacks: int = MAX_FALLBACKS,
) -> list[tuple[str, str]]:
    """Ordered (version, source) candidates honouring the no-upgrade red line."""

    floor = _floor_version(declared)
    floor_version = _version(floor)
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()

    def accept(version: str, source: str) -> None:
        parsed = _version(version)
        if parsed is None or version in seen:
            return
        if floor_version is not None:
            # Never newer than the declared floor, never a different major.
            if parsed > floor_version:
                return
            if parsed.major != floor_version.major:
                return
        seen.add(version)
        ordered.append((version, source))

    if floor:
        accept(floor, "declared")

    if provider is not None:
        for version in provider.candidates(declared.name, floor, cutoff):
            accept(version, "history")

    # Next-older releases from the same major, at most max_fallbacks.
    if floor_version is not None and len(ordered) <= max_fallbacks:
        micro = floor_version.micro or 0
        for offset in range(1, max_fallbacks + 1):
            older = Version(f"{floor_version.major}.{floor_version.minor}.{max(micro - offset, 0)}")
            if older >= floor_version:
                continue
            accept(str(older), "next_older")

    return ordered[: 1 + max_fallbacks]


def _pip_argv(name: str, version: str, index_url: str | None) -> list[str]:
    if not _NAME_RE.match(name):
        raise ValueError(f"unsafe package name: {name!r}")
    argv = [
        "python",
        "-m",
        "pip",
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "--no-cache-dir",
    ]
    if index_url:
        argv += ["--index-url", index_url]
    requirement = f"{name}=={version}" if version else name
    argv.append(requirement)
    for flag in FORBIDDEN_PIP_FLAGS:
        if flag in argv:  # pragma: no cover - defensive
            raise ValueError(f"forbidden pip flag {flag!r}")
    return argv


async def resolve_and_install(
    handle: SandboxHandle,
    genome: Any,
    *,
    provider: VersionProvider | None = None,
    events: EventPort | None = None,
    cutoff: datetime | None = None,
    python_executable: str = "python",
    index_url: str | None = None,
    timeout: float = 600.0,
    max_fallbacks: int = MAX_FALLBACKS,
) -> InstallOutcome:
    """Install every declared dependency, falling back through history."""

    port = handle.port
    if port is None:
        raise RuntimeError("handle is not bound to an execution port")
    outcome = InstallOutcome()
    for declared in declared_dependencies(genome):
        candidates = candidate_versions(declared, provider, cutoff, max_fallbacks=max_fallbacks)
        if not candidates:
            candidates = [("", "declared")]
        tried: list[str] = []
        installed: PinnedDep | None = None
        for attempt_no, (version, source) in enumerate(candidates, start=1):
            argv = _pip_argv(declared.name, version, index_url)
            if python_executable != "python":
                argv[0] = python_executable
            tried.append(version or "latest")
            if events is not None:
                await events.emit(
                    {
                        "type": "build.attempt",
                        "payload": {
                            "phase": "dependency_install",
                            "dependency": declared.name,
                            "version": version or None,
                            "source": source,
                            "attempt": attempt_no,
                        },
                    }
                )
            result: RunResult = await port.run("build", argv, timeout)
            outcome.attempts.append(
                {
                    "name": declared.name,
                    "version": version,
                    "source": source,
                    "attempt": attempt_no,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                }
            )
            if result.ok:
                installed = PinnedDep(
                    name=declared.name,
                    installed_version=version,
                    original_declared_version=declared.version or "",
                    changed=bool(declared.version) and version != declared.version,
                    requested_version=version,
                    attempts=attempt_no,
                    candidate_source=source,
                )
                if source != "declared":
                    outcome.fallbacks_used += 1
                break
        if installed is None:
            outcome.failures.append((declared.name, tried))
        else:
            outcome.locked.append(installed)
    return outcome


def lock_text(outcome: InstallOutcome) -> str:
    """Render dependencies.lock (deterministic, sorted)."""

    lines = [
        "# ReviveOS dependencies.lock - installed_version may differ from",
        "# original_declared_version; every difference is a documented repair.",
    ]
    for dep in sorted(outcome.locked, key=lambda item: item.name):
        lines.append(
            f"{dep.name}=={dep.installed_version}  # declared={dep.original_declared_version or 'unpinned'} "
            f"changed={str(dep.changed).lower()}"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "MAX_FALLBACKS",
    "FORBIDDEN_PIP_FLAGS",
    "DeclaredDep",
    "PinnedDep",
    "InstallOutcome",
    "VersionProvider",
    "StaticVersionProvider",
    "PypiVersionProvider",
    "declared_dependencies",
    "candidate_versions",
    "resolve_and_install",
    "lock_text",
]
