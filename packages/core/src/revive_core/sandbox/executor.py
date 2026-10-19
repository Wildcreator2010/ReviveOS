"""Execution port types and the sandbox security baseline (T-SB-02).

The Protocol declared here mirrors agents/src/revive_agents/ports.py one for
one; the concrete implementations live in port_impl.py.  Keeping the value
objects in core lets the runner, dep solver, patch flow, capsule builder and
CLI all share one vocabulary without importing the agents package.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# --------------------------------------------------------------------------
# Security baseline - every execution backend imports these constants instead
# of hard-coding flags, so a security review has exactly one place to read.
# --------------------------------------------------------------------------
SANDBOX_USER = "1000:1000"
TMPFS_SPEC = "/tmp:rw,noexec,nosuid,size=256m"
LABEL_KEY = "revive.job_id"
NETWORK_DISABLED = True
NO_NEW_PRIVILEGES = True
CPU_LIMIT = 2.0
MEM_LIMIT = "4g"
DISK_LIMIT = "10g"
DEFAULT_TIMEOUT = 300.0

#: The ONLY egress allowed anywhere in ReviveOS, and only during the dependency
#: installation phase of a build.
ALLOWED_BUILD_DOMAINS: tuple[str, ...] = (
    "pypi.org",
    "files.pythonhosted.org",
    "repo.anaconda.com",
    "registry-1.docker.io",
    "auth.docker.io",
    "production.cloudflare.docker.com",
)

#: Host paths that must never be bind-mounted into a sandbox container.
FORBIDDEN_MOUNTS: tuple[str, ...] = ("/", "~", "/root", "/home", "/etc", "/var/run/docker.sock")

#: Hard cap for a single in-memory buffer; anything larger is streamed to disk.
MAX_MEMORY_BUFFER = 8 * 1024 * 1024


class SandboxError(RuntimeError):
    """Base class for sandbox failures."""


class SandboxUnavailableError(SandboxError):
    """The requested backend cannot be used on this host (e.g. no Docker daemon)."""


@dataclass(frozen=True)
class ArtifactRef:
    """A streamed output file plus its content hash."""

    path: str
    sha256: str
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


@dataclass
class RunResult:
    """Outcome of one command inside the sandbox."""

    kind: str
    argv: list[str]
    exit_code: int
    stdout_ref: ArtifactRef | None = None
    stderr_ref: ArtifactRef | None = None
    duration: float = 0.0
    timed_out: bool = False
    backend: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout_ref": self.stdout_ref.to_dict() if self.stdout_ref else None,
            "stderr_ref": self.stderr_ref.to_dict() if self.stderr_ref else None,
            "duration": round(self.duration, 6),
            "timed_out": self.timed_out,
            "backend": self.backend,
            "ok": self.ok,
        }


@dataclass
class SandboxHandle:
    """Identity of a live sandbox workspace."""

    container_id: str
    ws_path: str
    digest: str | None
    job_id: str
    backend: str
    genome: Any = None
    image_plan: Any = None
    meta: dict[str, Any] = field(default_factory=dict)
    closed: bool = False
    _port: Any = None

    def bind_port(self, port: Any) -> SandboxHandle:
        object.__setattr__(self, "_port", port)
        return self

    @property
    def port(self) -> Any:
        return self._port


@dataclass(frozen=True)
class SnapshotToken:
    """Opaque token returned by snapshot_ws and accepted by restore_ws."""

    token: str
    path: str
    sha256: str
    bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }


@dataclass
class PatchResult:
    ok: bool
    applied_files: list[str] = field(default_factory=list)
    reason: str = ""
    conflict_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "applied_files": list(self.applied_files),
            "reason": self.reason,
            "conflict_files": list(self.conflict_files),
        }


class PatchConflict(SandboxError):
    """Raised when a patch cannot be applied cleanly to the workspace."""

    def __init__(self, reason: str, files: Iterable[str] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.files = list(files or [])


@runtime_checkable
class ExecutionPort(Protocol):
    """Structural mirror of revive_agents.ports.ExecutionPort."""

    async def ensure_env(self, genome: Any) -> SandboxHandle: ...

    async def run(self, kind: str, argv: list[str], timeout: float) -> RunResult: ...

    async def apply_patch(self, diff: str) -> PatchResult: ...

    async def snapshot_ws(self) -> SnapshotToken: ...

    async def restore_ws(self, token: Any) -> bool: ...


@runtime_checkable
class EventPort(Protocol):
    async def emit(self, event: dict[str, Any]) -> None: ...


class NullEventPort:
    """Discards events; the default for unit tests."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


def sandbox_tmpdir(prefix: str) -> Path:
    """Create a scratch dir, preferring the OS temp dir.

    Restricted hosts (including the DSH Windows sandbox) deny writes outside
    the workspace, so we fall back to <cwd>/.revive-tmp rather than failing.
    """

    candidates: list[Path] = []
    explicit = os.environ.get("REVIVE_TMP_DIR")
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path(tempfile.gettempdir()))
    candidates.append(Path.cwd() / ".revive-tmp")
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            # NOTE: tempfile.mkdtemp() is deliberately avoided.  The DSH Windows
            # sandbox grants write access to directories made with mkdir but not
            # to mkdtemp() directories, so we create our own and probe it.
            created = candidate / f"{prefix}{uuid.uuid4().hex[:12]}"
            created.mkdir()
        except OSError:
            continue
        try:
            probe = created / "revive-write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return created
        except OSError:
            shutil.rmtree(created, ignore_errors=True)
            continue
    raise SandboxError("no writable temporary directory is available")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_artifact(
    root: str | Path,
    rel_path: str,
    chunks: bytes | Iterable[bytes] | Iterator[bytes],
    *,
    memory_cap: int = MAX_MEMORY_BUFFER,
) -> ArtifactRef:
    """Stream chunks to root/rel_path, hashing as we go.

    The buffer is never larger than memory_cap: a bytes payload is written
    directly and iterables are written chunk by chunk.  Callers that already
    captured output pass bytes; port implementations stream process output.
    """

    destination = Path(root) / rel_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    with destination.open("wb") as handle:
        if isinstance(chunks, (bytes, bytearray)):
            payload = bytes(chunks)
            digest.update(payload)
            total = len(payload)
            handle.write(payload)
        else:
            for chunk in chunks:
                if not chunk:
                    continue
                digest.update(chunk)
                total += len(chunk)
                handle.write(chunk)
    return ArtifactRef(path=rel_path.replace("\\", "/"), sha256=digest.hexdigest(), bytes=total)


__all__ = [
    "SANDBOX_USER",
    "TMPFS_SPEC",
    "LABEL_KEY",
    "NETWORK_DISABLED",
    "NO_NEW_PRIVILEGES",
    "CPU_LIMIT",
    "MEM_LIMIT",
    "DISK_LIMIT",
    "DEFAULT_TIMEOUT",
    "ALLOWED_BUILD_DOMAINS",
    "FORBIDDEN_MOUNTS",
    "MAX_MEMORY_BUFFER",
    "SandboxError",
    "SandboxUnavailableError",
    "ArtifactRef",
    "RunResult",
    "SandboxHandle",
    "SnapshotToken",
    "PatchResult",
    "PatchConflict",
    "ExecutionPort",
    "EventPort",
    "NullEventPort",
    "sha256_bytes",
    "sandbox_tmpdir",
    "write_artifact",
]
