"""revive replay - re-enter a capsule workspace (T-CAP-03).

Non-interactive replay runs one command inside a materialised capsule
workspace; interactive replay hands a TTY to the container (docker backend).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import layout
from .verify import extract_capsule


@dataclass
class ReplayResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    workspace: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "workspace": self.workspace,
        }


async def replay(
    capsule: str | Path,
    port: Any,
    *,
    argv: list[str] | None = None,
    workspace: str | Path | None = None,
) -> ReplayResult:
    """Materialise the capsule and run one command in the given port."""

    from ..sandbox.executor import sandbox_tmpdir

    target = Path(workspace) if workspace else sandbox_tmpdir("revive-replay-")
    extract_capsule(capsule, target)
    handle = await port.ensure_env(None)
    if hasattr(port, "workspace"):
        port.workspace = target  # local backend: point it at the capsule tree
        handle.ws_path = str(target)
    command = list(argv or ["python", "-c", "print('revive replay: no command supplied')"])
    result = await port.run("replay", command, 120.0)
    stdout = _read(port, target, result.stdout_ref)
    stderr = _read(port, target, result.stderr_ref)
    return ReplayResult(
        argv=command,
        exit_code=result.exit_code,
        stdout=stdout,
        stderr=stderr,
        workspace=str(target),
    )


def _read(port: Any, target: Path, ref: Any) -> str:
    if ref is None:
        return ""
    root = getattr(port, "artifacts_dir", None)
    if root is not None:
        path = Path(root) / ref.path
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def capsule_manifest(capsule: str | Path) -> dict[str, Any]:
    """Read just manifest.json from a capsule."""

    import tarfile

    with tarfile.open(capsule, mode="r:gz") as archive:
        member = archive.getmember(layout.MANIFEST)
        stream = archive.extractfile(member)
        if stream is None:  # pragma: no cover
            raise ValueError("manifest.json is empty")
        return json.loads(stream.read().decode("utf-8"))


__all__ = ["ReplayResult", "replay", "capsule_manifest"]
