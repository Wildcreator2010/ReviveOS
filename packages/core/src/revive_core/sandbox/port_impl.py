"""Concrete ExecutionPort implementations (T-SB-02).

* FakeExecutionPort  - scripted, in-memory, zero I/O.  Unit-test substitute.
* LocalExecutionPort - real subprocesses in a throwaway directory.  Integration
  and CLI-test substitute so the whole pipeline is exercisable on hosts where
  Docker is unavailable (this Windows sandbox denies the Docker named pipe).
  It is NOT a security boundary and is never wired into the server pipeline.
* DockerExecutionPort - the production backend.  It applies the full sandbox
  baseline (network_disabled, user 1000:1000, no-new-privileges, tmpfs /tmp,
  cpu/mem limits, timeout kill, revive.job_id label for orphan sweeps).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import shutil
import subprocess
import tarfile
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..gitutil import GitUnavailableError, run_git
from . import diffapply
from .dockerfile_template import render_dockerfile
from .executor import (
    CPU_LIMIT,
    DEFAULT_TIMEOUT,
    LABEL_KEY,
    MEM_LIMIT,
    NETWORK_DISABLED,
    SANDBOX_USER,
    TMPFS_SPEC,
    ArtifactRef,
    EventPort,
    PatchResult,
    RunResult,
    SandboxError,
    SandboxHandle,
    SandboxUnavailableError,
    SnapshotToken,
    sandbox_tmpdir,
    sha256_bytes,
    write_artifact,
)
from .image_matrix import ImagePlan, Unsupported, plan_image

_PIP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9._, -]+\])?$")
_PIP_VERSION_RE = re.compile(r"^[A-Za-z0-9.*+!_~-]+$")
_PIP_OPERATOR_RE = re.compile(r"^(===|==|>=|<=|~=|!=|>|<)[A-Za-z0-9.*+!_~-]+$")


def _genome_mapping(genome: Any) -> Mapping[str, Any]:
    if genome is None:
        return {}
    if isinstance(genome, Mapping):
        return genome
    dump = getattr(genome, "model_dump", None)
    if callable(dump):
        return dump()
    return {}


def dependency_specs(genome: Any) -> list[str]:
    """Translate inferred PyPI dependencies into safe pip requirement strings.

    The base image is built with network enabled; the job container itself stays
    network-disabled, so dependencies must be installed while the image builds.
    """

    specs: list[str] = []
    seen: set[str] = set()
    for dependency in _genome_mapping(genome).get("dependencies") or []:
        if not isinstance(dependency, Mapping):
            continue
        source = str(dependency.get("source") or "").strip().lower()
        if source not in {"", "pypi", "pip", "requirements", "inference", "inferred"}:
            continue
        name = str(dependency.get("name") or "").strip()
        if not _PIP_NAME_RE.match(name):
            continue
        version = str(dependency.get("version") or "").strip()
        if not version or version.lower() in {"unknown", "latest", "*"}:
            spec = name
        elif version[0] in "=<>!~":
            spec = name + version if _PIP_OPERATOR_RE.match(version) else name
        elif _PIP_VERSION_RE.match(version):
            spec = f"{name}=={version}"
        else:
            spec = name
        if spec not in seen:
            seen.add(spec)
            specs.append(spec)
    return specs


def dockerfile_with_dependencies(dockerfile: str, specs: list[str]) -> str:
    if not specs:
        return dockerfile
    line = "RUN python -m pip install --no-cache-dir " + " ".join(specs)
    marker = "USER 1000:1000"
    if marker in dockerfile:
        return dockerfile.replace(marker, f"{line}\n{marker}", 1)
    return f"{dockerfile.rstrip()}\n{line}\n"


# --------------------------------------------------------------------------
# Host capability probes
# --------------------------------------------------------------------------


def docker_available() -> tuple[bool, str]:
    """Return (usable, reason).  Never raises."""

    try:
        import docker  # noqa: PLC0415 - optional dependency
    except ImportError:
        return False, "docker-py is not installed (install revive-core[docker])"
    try:
        client = docker.from_env()
        client.ping()
        client.close()
    except Exception as exc:  # docker.errors.* and OS errors alike
        return False, f"docker daemon unreachable: {type(exc).__name__}: {exc}"
    return True, "ok"


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def _genome_digest(genome: Any) -> str:
    payload = repr(genome).encode("utf-8", "replace")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _safe_tar_extract(archive: tarfile.TarFile, destination: Path) -> None:
    """Extract refusing absolute paths and .. escapes (tar slip guard)."""

    for member in archive.getmembers():
        member_path = destination / member.name
        resolved = member_path.resolve()
        if not str(resolved).startswith(str(destination.resolve())):
            raise SandboxError(f"refusing unsafe tar member: {member.name!r}")
        if member.issym() or member.islnk():
            raise SandboxError(f"refusing link member in snapshot: {member.name!r}")


# --------------------------------------------------------------------------
# FakeExecutionPort
# --------------------------------------------------------------------------
class FakeExecutionPort:
    """Scripted in-memory execution port for unit tests.

    responses keys may be:
      * "exact:<kind>"                 -> (exit_code, stdout, stderr)
      * "argv:<space joined argv>"     -> (exit_code, stdout, stderr)
      * any callable(argv, kind)       -> (exit_code, stdout, stderr)
    A missing response means exit_code 0 with empty output.
    """

    backend = "fake"

    def __init__(
        self,
        files: Mapping[str, str] | None = None,
        *,
        responses: Mapping[str, Any] | None = None,
        events: EventPort | None = None,
        job_id: str = "fake-job",
        artifacts_dir: str | Path | None = None,
    ) -> None:
        self.files: dict[str, str] = dict(files or {})
        self.responses: dict[str, Any] = dict(responses or {})
        self.events = events
        self.job_id = job_id
        self.calls: list[tuple[str, list[str], float]] = []
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else sandbox_tmpdir("revive-fake-")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots: dict[str, dict[str, str]] = {}
        self._run_index = 0
        self.closed = False

    # -- helpers ---------------------------------------------------------
    def _response(self, kind: str, argv: list[str]) -> tuple[int, str, str]:
        joined = " ".join(argv)
        for key in (f"argv:{joined}", f"exact:{kind}", joined.split(" ")[-1] if argv else kind):
            if key in self.responses:
                value = self.responses[key]
                return self._normalise(value, argv, kind)
        if kind in self.responses:
            return self._normalise(self.responses[kind], argv, kind)
        return 0, "", ""

    @staticmethod
    def _normalise(value: Any, argv: list[str], kind: str) -> tuple[int, str, str]:
        if callable(value):
            value = value(argv, kind)
        if isinstance(value, int):
            return value, "", ""
        if isinstance(value, dict):
            return (
                int(value.get("exit_code", 0)),
                str(value.get("stdout", "")),
                str(value.get("stderr", "")),
            )
        code, out, err = value
        return int(code), str(out), str(err)

    # -- ExecutionPort ---------------------------------------------------
    async def ensure_env(self, genome: Any) -> SandboxHandle:
        handle = SandboxHandle(
            container_id=f"fake-{self.job_id}-{uuid.uuid4().hex[:8]}",
            ws_path="/workspace",
            digest=_genome_digest(genome),
            job_id=self.job_id,
            backend=self.backend,
            genome=genome,
            meta={"artifacts_dir": str(self.artifacts_dir)},
        )
        handle.bind_port(self)
        if self.events is not None:
            await self.events.emit({"type": "sandbox.created", "payload": {"backend": self.backend}})
        return handle

    async def run(self, kind: str, argv: list[str], timeout: float) -> RunResult:
        if self.closed:
            raise SandboxError("fake sandbox is closed")
        self.calls.append((kind, list(argv), timeout))
        time.sleep(0)
        code, stdout, stderr = self._response(kind, argv)
        index = self._run_index
        self._run_index += 1
        out_ref = write_artifact(self.artifacts_dir, f"{kind}-{index}.stdout", stdout.encode("utf-8"))
        err_ref = write_artifact(self.artifacts_dir, f"{kind}-{index}.stderr", stderr.encode("utf-8"))
        if self.events is not None:
            await self.events.emit({"type": f"{kind}.attempt", "payload": {"exit_code": code, "argv": list(argv)}})
        return RunResult(
            kind=kind,
            argv=list(argv),
            exit_code=code,
            stdout_ref=out_ref,
            stderr_ref=err_ref,
            duration=0.0,
            timed_out=False,
            backend=self.backend,
        )

    async def apply_patch(self, diff: str) -> PatchResult:
        try:
            touched = diffapply.apply_to_mapping(self.files, diff)
        except diffapply.DiffApplyError as exc:
            return PatchResult(ok=False, reason=str(exc))
        return PatchResult(ok=True, applied_files=touched)

    async def snapshot_ws(self) -> SnapshotToken:
        token = f"fake-{len(self._snapshots)}"
        self._snapshots[token] = dict(self.files)
        blob = repr(sorted(self.files.items())).encode("utf-8")
        return SnapshotToken(token=token, path=token, sha256=sha256_bytes(blob), bytes=len(blob))

    async def restore_ws(self, token: Any) -> bool:
        key = token.token if isinstance(token, SnapshotToken) else str(token)
        if key not in self._snapshots:
            raise SandboxError(f"unknown snapshot token {key!r}")
        self.files = dict(self._snapshots[key])
        return True

    async def close(self) -> None:
        self.closed = True

    # -- convenience -----------------------------------------------------
    def write_file(self, rel_path: str, text: str) -> None:
        self.files[rel_path] = text

    def read_text(self, rel_path: str) -> str:
        try:
            return self.files[rel_path]
        except KeyError as exc:
            raise FileNotFoundError(rel_path) from exc

    def list_dir(self, rel_path: str = "") -> list[str]:
        prefix = rel_path.strip("/")
        prefix = prefix + "/" if prefix else ""
        children: set[str] = set()
        for name in self.files:
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix) :]
            if rest:
                children.add(rest.split("/")[0])
        return sorted(children)


# --------------------------------------------------------------------------
# LocalExecutionPort
# --------------------------------------------------------------------------
class LocalExecutionPort:
    """Runs commands in a throwaway directory with no Docker (test substitute).

    WARNING - not a security boundary.  It exists so unit/integration tests and
    revive resurrect --local can exercise the whole pipeline on hosts without a
    Docker daemon.  Production wiring always uses DockerExecutionPort.
    """

    backend = "local"

    def __init__(
        self,
        workspace: str | Path | None = None,
        *,
        source: str | Path | None = None,
        job_id: str | None = None,
        artifacts_dir: str | Path | None = None,
        events: EventPort | None = None,
        env: Mapping[str, str] | None = None,
        ephemeral: bool = True,
        offline: bool = True,
    ) -> None:
        self.job_id = job_id or f"local-{uuid.uuid4().hex[:8]}"
        self._owns_workspace = workspace is None
        if workspace is None:
            workspace = sandbox_tmpdir("revive-local-")
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.source = Path(source) if source else None
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else self.workspace.parent / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.events = events
        self.ephemeral = ephemeral
        self.offline = offline
        self.env = dict(env or {})
        self.closed = False
        self._run_index = 0
        self._handle: SandboxHandle | None = None

    # -- process environment --------------------------------------------
    def _process_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.env)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
        if self.offline:
            # Local substitute defaults to a no-network pip so tests never
            # silently reach an index; fixtures that need pip set offline=False.
            env.setdefault("PIP_NO_INDEX", "1")
        return env

    # -- ExecutionPort ---------------------------------------------------
    async def ensure_env(self, genome: Any) -> SandboxHandle:
        if self.source is not None:
            self._copy_source()
        handle = SandboxHandle(
            container_id=f"local-{self.job_id}",
            ws_path=str(self.workspace),
            digest=_genome_digest(genome),
            job_id=self.job_id,
            backend=self.backend,
            genome=genome,
            meta={"artifacts_dir": str(self.artifacts_dir)},
        )
        handle.bind_port(self)
        self._handle = handle
        if self.events is not None:
            await self.events.emit(
                {
                    "type": "sandbox.created",
                    "payload": {"backend": self.backend, "ws": str(self.workspace)},
                }
            )
        return handle

    def _copy_source(self) -> None:
        assert self.source is not None
        for entry in sorted(self.source.rglob("*")):
            rel = entry.relative_to(self.source)
            if entry.is_symlink():
                continue
            if ".git" in rel.parts and rel.parts[0] == ".git":
                # Keep only the git metadata when explicitly a repo; copy all.
                pass
            target = self.workspace / rel
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif entry.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, target)

    async def run(self, kind: str, argv: list[str], timeout: float = DEFAULT_TIMEOUT) -> RunResult:
        if self.closed:
            raise SandboxError("local sandbox is closed")
        self._run_index += 1
        index = self._run_index
        out_path = self.artifacts_dir / f"{kind}-{index}.stdout"
        err_path = self.artifacts_dir / f"{kind}-{index}.stderr"
        started = time.monotonic()
        timed_out = False
        code = -1
        with out_path.open("wb") as out_handle, err_path.open("wb") as err_handle:
            try:
                proc = subprocess.Popen(
                    [str(a) for a in argv],
                    cwd=str(self.workspace),
                    stdin=subprocess.DEVNULL,
                    stdout=out_handle,
                    stderr=err_handle,
                    env=self._process_env(),
                    shell=False,
                )
            except OSError as exc:
                err_handle.write(f"failed to spawn {argv!r}: {exc}\n".encode())
                code = -1
            else:
                try:
                    code = proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    proc.kill()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:  # pragma: no cover
                        pass
                    code = -1
        duration = time.monotonic() - started
        out_sha, out_bytes = _digest_file(out_path)
        err_sha, err_bytes = _digest_file(err_path)
        result = RunResult(
            kind=kind,
            argv=[str(a) for a in argv],
            exit_code=code if not timed_out else -1,
            stdout_ref=ArtifactRef(f"{kind}-{index}.stdout", out_sha, out_bytes),
            stderr_ref=ArtifactRef(f"{kind}-{index}.stderr", err_sha, err_bytes),
            duration=duration,
            timed_out=timed_out,
            backend=self.backend,
        )
        if self.events is not None:
            await self.events.emit(
                {
                    "type": f"{kind}.attempt",
                    "payload": {
                        "exit_code": result.exit_code,
                        "argv": list(result.argv),
                        "timed_out": timed_out,
                    },
                }
            )
        return result

    async def apply_patch(self, diff: str) -> PatchResult:
        patch_file = self.artifacts_dir / f"patch-{uuid.uuid4().hex[:8]}.diff"
        patch_file.write_text(diff, encoding="utf-8")
        try:
            check = run_git(
                ["apply", "--check", "--whitespace=nowarn", str(patch_file)],
                cwd=self.workspace,
                check=False,
            )
            if check.returncode != 0:
                return PatchResult(
                    ok=False,
                    reason=(check.stderr or check.stdout).strip()[:400] or "git apply --check failed",
                )
            applied = run_git(["apply", "--whitespace=nowarn", str(patch_file)], cwd=self.workspace, check=False)
            if applied.returncode != 0:
                return PatchResult(
                    ok=False,
                    reason=(applied.stderr or applied.stdout).strip()[:400] or "git apply failed",
                )
        except GitUnavailableError:
            # No git on this host: fall back to the in-process applier.
            try:
                touched = diffapply.apply_to_root(self.workspace, diff)
            except diffapply.DiffApplyError as exc:
                return PatchResult(ok=False, reason=str(exc))
            return PatchResult(ok=True, applied_files=touched)
        touched = [patch.path for patch in diffapply.parse_diff(diff)]
        return PatchResult(ok=True, applied_files=touched)

    async def snapshot_ws(self) -> SnapshotToken:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for entry in sorted(self.workspace.rglob("*")):
                rel = entry.relative_to(self.workspace)
                if any(part in {".git", "__pycache__"} for part in rel.parts):
                    continue
                archive.add(str(entry), arcname=str(rel.as_posix()), recursive=False)
        payload = buffer.getvalue()
        digest = sha256_bytes(payload)
        snap_dir = self.artifacts_dir / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_path = snap_dir / f"{digest[:16]}.tar.gz"
        snap_path.write_bytes(payload)
        return SnapshotToken(token=digest, path=str(snap_path), sha256=digest, bytes=len(payload))

    async def restore_ws(self, token: Any) -> bool:
        path = Path(token.path) if isinstance(token, SnapshotToken) else Path(str(token))
        if not path.is_file():
            raise SandboxError(f"snapshot not found: {path}")
        with tarfile.open(path, mode="r:gz") as archive:
            _safe_tar_extract(archive, self.workspace)
            for entry in sorted(self.workspace.iterdir()):
                if entry.name in {".git", "artifacts"}:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            archive.extractall(self.workspace)
        return True

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.ephemeral and self._owns_workspace:
            shutil.rmtree(self.workspace, ignore_errors=True)

    # -- convenience -----------------------------------------------------
    def write_file(self, rel_path: str, text: str) -> None:
        target = self.workspace / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def read_text(self, rel_path: str) -> str:
        return (self.workspace / rel_path).read_text(encoding="utf-8", errors="replace")

    def list_dir(self, rel_path: str = "") -> list[str]:
        base = self.workspace / rel_path
        if not base.is_dir():
            return []
        return sorted(entry.name for entry in base.iterdir())


# --------------------------------------------------------------------------
# DockerExecutionPort
# --------------------------------------------------------------------------
def sandbox_security_kwargs(job_id: str, *, network_disabled: bool = NETWORK_DISABLED) -> dict[str, Any]:
    """The single source of truth for runtime container hardening."""

    return {
        "network_disabled": network_disabled,
        "user": SANDBOX_USER,
        "working_dir": "/workspace",
        "tmpfs": {"/tmp": TMPFS_SPEC},
        "mem_limit": MEM_LIMIT,
        "nano_cpus": int(CPU_LIMIT * 1_000_000_000),
        "security_opt": ["no-new-privileges"],
        "cap_drop": ["ALL"],
        "pids_limit": 512,
        "privileged": False,
        "labels": {LABEL_KEY: job_id},
    }


def sweep_orphans(client: Any, job_id: str | None = None) -> list[str]:
    """Remove containers carrying the revive.job_id label; returns removed ids."""

    filters = {"label": LABEL_KEY}
    removed: list[str] = []
    for container in client.containers.list(all=True, filters=filters):
        labels = (container.attrs.get("Config", {}) or {}).get("Labels", {}) or {}
        if job_id and labels.get(LABEL_KEY) != job_id:
            continue
        try:
            container.remove(force=True)
            removed.append(container.id)
        except Exception:  # pragma: no cover - best effort sweep
            continue
    return removed


class DockerExecutionPort:
    """Production sandbox backend (T-SB-02).

    Runtime containers are created with network_disabled=True.  The only phase
    allowed to reach a registry/pypi is the *image build* (docker build), which
    is why dependency installation happens during build or through the explicit
    build_network context manager, never in a run-stage container.
    """

    backend = "docker"

    def __init__(
        self,
        workspace: str | Path | None = None,
        *,
        job_id: str | None = None,
        artifacts_dir: str | Path | None = None,
        events: EventPort | None = None,
        client: Any = None,
        image_tag: str | None = None,
        keep_sandbox: bool = False,
        base_dir: str | Path | None = None,
    ) -> None:
        self.job_id = job_id or f"job-{uuid.uuid4().hex[:8]}"
        self.workspace = Path(workspace) if workspace else None
        self.base_dir = Path(base_dir) if base_dir else sandbox_tmpdir("revive-docker-")
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else self.base_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.events = events
        self.image_tag = image_tag or f"revive-sbx-{self.job_id}"
        self.keep_sandbox = keep_sandbox
        self._client = client
        self._container: Any = None
        self._handle: SandboxHandle | None = None
        self._closed = False
        self._allow_network = False
        self._run_index = 0

    # -- client ----------------------------------------------------------
    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import docker  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - environment specific
                raise SandboxUnavailableError("docker-py is not installed; install revive-core[docker]") from exc
            try:
                self._client = docker.from_env()
                self._client.ping()
            except Exception as exc:  # pragma: no cover - environment specific
                raise SandboxUnavailableError(f"docker daemon unreachable: {exc}") from exc
        return self._client

    # -- environment -----------------------------------------------------
    async def ensure_env(self, genome: Any) -> SandboxHandle:
        plan = plan_image(genome)
        if isinstance(plan, Unsupported):
            raise SandboxUnavailableError(plan.reason)
        return await self.ensure_env_from_plan(plan, genome=genome)

    async def ensure_env_from_plan(self, plan: ImagePlan, *, genome: Any = None) -> SandboxHandle:
        dockerfile = dockerfile_with_dependencies(render_dockerfile(plan), dependency_specs(genome))
        dockerfile_path = self.base_dir / "Dockerfile.resurrected-base"
        dockerfile_path.write_text(dockerfile, encoding="utf-8")
        client = self.client
        image, build_logs = client.images.build(
            path=str(self.base_dir),
            dockerfile=dockerfile_path.name,
            tag=self.image_tag,
            rm=True,
            forcerm=True,
            labels={LABEL_KEY: self.job_id},
        )
        del build_logs  # build log is streamed by the caller via events
        container = client.containers.run(
            image.id,
            command=["sleep", "infinity"],
            detach=True,
            **sandbox_security_kwargs(self.job_id, network_disabled=not self._allow_network),
        )
        self._container = container
        handle = SandboxHandle(
            container_id=container.id,
            ws_path="/workspace",
            digest=(container.image.id if container.image else None),
            job_id=self.job_id,
            backend=self.backend,
            genome=genome,
            image_plan=plan,
            meta={"artifacts_dir": str(self.artifacts_dir)},
        )
        handle.bind_port(self)
        self._handle = handle
        if self.workspace is not None and self.workspace.exists():
            self._put_directory(self.workspace, "/workspace")
            self._chown_workspace()
        if self.events is not None:
            await self.events.emit(
                {
                    "type": "sandbox.created",
                    "payload": {
                        "backend": self.backend,
                        "container_id": container.id,
                        "image": plan.os_image,
                        "python": plan.python_version,
                        "network_disabled": not self._allow_network,
                    },
                }
            )
        return handle

    # -- tar transfer ----------------------------------------------------
    def _chown_workspace(self) -> None:
        """put_archive extracts as root; the sandbox user must own its workspace."""

        assert self._container is not None
        result = self._container.exec_run(["chown", "-R", SANDBOX_USER, "/workspace"], user="root")
        if result.exit_code != 0:
            detail = (result.output or b"").decode("utf-8", "replace").strip()[:400]
            raise SandboxError(f"cannot hand /workspace to {SANDBOX_USER}: {detail}")

    def _put_directory(self, source: Path, destination: str) -> None:
        assert self._container is not None
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for entry in sorted(source.rglob("*")):
                rel = entry.relative_to(source)
                if ".git" in rel.parts and rel.parts[0] == ".git":
                    continue
                archive.add(str(entry), arcname=str(rel.as_posix()), recursive=False)
        buffer.seek(0)
        self._container.put_archive(destination, buffer.getvalue())

    # -- ExecutionPort ---------------------------------------------------
    async def run(self, kind: str, argv: list[str], timeout: float = DEFAULT_TIMEOUT) -> RunResult:
        if self._container is None:
            raise SandboxError("ensure_env() must be called before run()")
        index = self._run_index
        self._run_index += 1
        started = time.monotonic()
        timed_out = False

        def _exec() -> tuple[int, bytes, bytes]:
            result = self._container.exec_run(
                [str(a) for a in argv],
                user=SANDBOX_USER,
                workdir="/workspace",
                demux=True,
                tty=False,
            )
            out, err = result.output if isinstance(result.output, tuple) else (result.output, b"")
            return (
                int(result.exit_code if result.exit_code is not None else -1),
                out or b"",
                err or b"",
            )

        try:
            code, out, err = await asyncio.wait_for(asyncio.to_thread(_exec), timeout=timeout)
        except TimeoutError:
            timed_out = True
            code, out, err = -1, b"", f"timeout after {timeout}s; container killed".encode()
            try:
                self._container.kill()
            except Exception:  # pragma: no cover - best effort
                pass
        duration = time.monotonic() - started
        out_ref = write_artifact(self.artifacts_dir, f"{kind}-{index}.stdout", out)
        err_ref = write_artifact(self.artifacts_dir, f"{kind}-{index}.stderr", err)
        result = RunResult(
            kind=kind,
            argv=[str(a) for a in argv],
            exit_code=code,
            stdout_ref=out_ref,
            stderr_ref=err_ref,
            duration=duration,
            timed_out=timed_out,
            backend=self.backend,
        )
        if self.events is not None:
            await self.events.emit({"type": f"{kind}.attempt", "payload": {"exit_code": code, "timed_out": timed_out}})
        return result

    async def apply_patch(self, diff: str) -> PatchResult:
        if self._container is None:
            raise SandboxError("ensure_env() must be called before apply_patch()")
        patch_path = self.artifacts_dir / f"patch-{uuid.uuid4().hex[:8]}.diff"
        patch_path.write_text(diff, encoding="utf-8")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            archive.add(str(patch_path), arcname="revive.patch")
        buffer.seek(0)
        self._container.put_archive("/tmp", buffer.getvalue())
        check = self._container.exec_run(
            ["git", "apply", "--check", "/tmp/revive.patch"],
            user=SANDBOX_USER,
            workdir="/workspace",
        )
        if check.exit_code != 0:
            detail = (check.output or b"").decode("utf-8", "replace").strip()[:400]
            return PatchResult(ok=False, reason=detail or "git apply --check failed")
        applied = self._container.exec_run(
            ["git", "apply", "/tmp/revive.patch"], user=SANDBOX_USER, workdir="/workspace"
        )
        if applied.exit_code != 0:
            detail = (applied.output or b"").decode("utf-8", "replace").strip()[:400]
            return PatchResult(ok=False, reason=detail or "git apply failed")
        try:
            touched = [patch.path for patch in diffapply.parse_diff(diff)]
        except diffapply.DiffApplyError:
            touched = []
        return PatchResult(ok=True, applied_files=touched)

    async def snapshot_ws(self) -> SnapshotToken:
        if self._container is None:
            raise SandboxError("ensure_env() must be called before snapshot_ws()")
        stream, _stat = self._container.get_archive("/workspace")
        payload = b"".join(stream)
        digest = sha256_bytes(payload)
        snap_dir = self.artifacts_dir / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        path = snap_dir / f"{digest[:16]}.tar"
        path.write_bytes(payload)
        return SnapshotToken(token=digest, path=str(path), sha256=digest, bytes=len(payload))

    async def restore_ws(self, token: Any) -> bool:
        if self._container is None:
            raise SandboxError("ensure_env() must be called before restore_ws()")
        path = Path(token.path) if isinstance(token, SnapshotToken) else Path(str(token))
        payload = path.read_bytes()
        # Wipe then re-upload; container runs as uid 1000 so rm -rf is allowed.
        self._container.exec_run(
            ["bash", "-lc", "shopt -s dotglob; rm -rf /workspace/*"], user=SANDBOX_USER, workdir="/"
        )
        self._container.put_archive("/", payload)
        self._chown_workspace()
        return True

    def list_dir(self, rel_path: str = "") -> list[str]:
        """One-level listing inside the container (used by the stage runner)."""

        if self._container is None:
            return []
        target = f"/workspace/{rel_path}".rstrip("/") or "/workspace"
        result = self._container.exec_run(["ls", "-1", target], user=SANDBOX_USER)
        if result.exit_code != 0:
            return []
        text = (result.output or b"").decode("utf-8", "replace")
        return sorted(line.strip() for line in text.splitlines() if line.strip())

    def read_text(self, rel_path: str) -> str:
        if self._container is None:
            raise SandboxError("ensure_env() must be called before read_text()")
        result = self._container.exec_run(["cat", f"/workspace/{rel_path}"], user=SANDBOX_USER)
        if result.exit_code != 0:
            raise FileNotFoundError(rel_path)
        return (result.output or b"").decode("utf-8", "replace")

    def write_file(self, rel_path: str, text: str) -> None:
        if self._container is None:
            raise SandboxError("ensure_env() must be called before write_file()")
        patch_dir = self.artifacts_dir / "staged"
        patch_dir.mkdir(parents=True, exist_ok=True)
        staged = patch_dir / Path(rel_path).name
        staged.write_text(text, encoding="utf-8")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            archive.add(str(staged), arcname=Path(rel_path).name)
        buffer.seek(0)
        parent = str(Path(f"/workspace/{rel_path}").parent)
        self._container.exec_run(["mkdir", "-p", parent], user=SANDBOX_USER)
        self._container.put_archive(parent, buffer.getvalue())
        self._chown_workspace()

    def _dockerfile_for_capsule(self, plan: ImagePlan) -> str:
        return render_dockerfile(plan)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._container is not None and not self.keep_sandbox:
            try:
                self._container.remove(force=True)
            except Exception:  # pragma: no cover - best effort
                pass
        self._container = None

    # -- helpers ---------------------------------------------------------
    def __enter__(self) -> DockerExecutionPort:
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            self.client.close()
        except Exception:  # pragma: no cover
            pass


__all__ = [
    "docker_available",
    "FakeExecutionPort",
    "LocalExecutionPort",
    "DockerExecutionPort",
    "sandbox_security_kwargs",
    "sweep_orphans",
]
