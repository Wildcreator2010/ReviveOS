"""Deterministic .revive capsule builder (T-CAP-02).

Properties the builder guarantees:

* byte-identical output for the same RunState (sorted entries, fixed mtime,
  fixed gzip level, uid/gid/uname/gname normalised, no wall-clock timestamps);
* manifest.json passes revive-manifest.schema.json before anything is written;
* every entry is listed with its sha256 in digests.json;
* the finished archive is read back and self-verified (schema + digests);
* no LLM key, host absolute path or .git metadata can leak into the archive.

Format note: the work order text says tar.zst, but the platform dependency set
has no zstd binding, so the capsule is a deterministic tar.gz.  Determinism -
not the compression codec - is what content addressing needs, and gzip with
mtime=0 gives byte-identical rebuilds.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tarfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import schemas
from . import layout

GZIP_LEVEL = 9
_IGNORED_SOURCE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".revive-tmp",
    ".mypy_cache",
    ".pytest_cache",
}


class CapsuleBuildError(RuntimeError):
    """The capsule could not be built or failed self-verification."""


@dataclass
class RunState:
    """Everything the capsule needs; assembled by the pipeline / CLI."""

    job_id: str
    source_repo: str
    source_commit: str
    genome: dict[str, Any]
    dockerfile: str
    score: Any = None
    dependencies_lock: str = ""
    patches: list[tuple[str, str]] = field(default_factory=list)
    behavior_plan: dict[str, Any] = field(default_factory=dict)
    fingerprints: dict[str, Any] | None = None
    behavior_traces: list[str] = field(default_factory=list)
    behavior_compatibility: float | None = None
    status: str | None = None
    sbom: dict[str, Any] | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    llm_traces: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    created_at: str = ""
    source_tree: str | Path | None = None
    redistributable: bool = True

    def resolved_status(self) -> str:
        if self.status:
            return self.status
        status = getattr(self.score, "status", None)
        if isinstance(self.score, Mapping):
            status = self.score.get("status", status)
        return str(status or "partial")


def _canonical_json(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _epoch(created_at: str) -> int:
    if not created_at:
        return 0
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _score_dict(score: Any) -> dict[str, Any]:
    if score is None:
        raise CapsuleBuildError("RunState.score is required (no fabricated scores in a capsule)")
    if hasattr(score, "to_dict"):
        return dict(score.to_dict())
    if isinstance(score, Mapping):
        return dict(score)
    raise CapsuleBuildError(f"unsupported score object: {type(score)!r}")


def _sanitize(text: str, *, root: Path | None, home: Path | None) -> str:
    if root:
        text = text.replace(str(root), "<workspace>")
        text = text.replace(str(root).replace("\\", "/"), "<workspace>")
    if home:
        text = text.replace(str(home), "<home>")
    return text


def generate_sbom(state: RunState) -> dict[str, Any]:
    """Return state.sbom, or derive a CycloneDX document from the genome.

    Syft normally runs in a tool container; when Docker is unavailable the
    fallback is honest about its origin instead of pretending Syft ran.
    """

    if state.sbom is not None:
        return state.sbom
    components: list[dict[str, Any]] = []
    for dep in state.genome.get("dependencies", []) or []:
        components.append(
            {
                "type": "library",
                "name": str(dep.get("name", "")),
                "version": str(dep.get("version", "") or ""),
                "properties": [{"name": "revive:declared_source", "value": str(dep.get("source", ""))}],
            }
        )
    python_version = (state.genome.get("python") or {}).get("version") or ""
    components.append(
        {
            "type": "platform",
            "name": "python",
            "version": str(python_version),
            "properties": [{"name": "revive:runtime", "value": "true"}],
        }
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": state.created_at or "",
            "tools": [
                {
                    "vendor": "ReviveOS",
                    "name": "revive-core",
                    "version": "0.1.0",
                    "externalReferences": [
                        {
                            "type": "other",
                            "url": "https://reviveos.dev/sbom-fallback",
                            "comment": "syft unavailable (no Docker daemon); component list derived from the environment genome",  # noqa: E501
                        }
                    ],
                }
            ],
            "component": {"type": "application", "name": state.job_id or "revived-project"},
        },
        "components": components,
    }


def _source_tar(source_tree: Path, timestamp: int) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for entry in sorted(source_tree.rglob("*")):
            rel = entry.relative_to(source_tree)
            if any(part in _IGNORED_SOURCE_DIRS for part in rel.parts):
                continue
            # A cloned repository can contain symlinks to host paths; packaging the
            # link target would leak files outside the workspace.
            if entry.is_symlink() or not entry.is_file():
                continue
            payload = entry.read_bytes()
            info = tarfile.TarInfo(str(rel.as_posix()))
            info.size = len(payload)
            info.mtime = timestamp
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _tar_gz(entries: list[tuple[str, bytes]], timestamp: int) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0, compresslevel=GZIP_LEVEL, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, payload in sorted(entries, key=lambda item: item[0]):
                layout.check_entry_name(name)
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mtime = timestamp
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _secret_values() -> list[str]:
    names = ("REVIVE_LLM__API_KEY", "REVIVE_JWT__SECRET", "S3_SECRET_KEY")
    values = [os.environ.get(name, "") for name in names]
    return [value for value in values if value and len(value) >= 8]


def _assert_clean(entries: Iterable[tuple[str, bytes]], *, root: Path | None, home: Path | None) -> None:
    secrets = _secret_values()
    for name, payload in entries:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for secret in secrets:
            if secret in text:
                raise CapsuleBuildError(f"refusing to package a credential into {name}")
        if root and str(root) in text:
            raise CapsuleBuildError(f"host workspace path leaked into {name}")
        if home and str(home) in text:
            raise CapsuleBuildError(f"host home path leaked into {name}")


def build_entries(state: RunState) -> list[tuple[str, bytes]]:
    """Assemble the capsule's logical entries (without digests.json)."""

    root = Path.cwd()
    home = Path(os.path.expanduser("~"))
    score = _score_dict(state.score)
    sbom = generate_sbom(state)
    sbom_bytes = _canonical_json(sbom)
    sbom_digest = hashlib.sha256(sbom_bytes).hexdigest()

    patch_entries: list[str] = []
    patch_payloads: list[tuple[str, bytes]] = []
    for index, (name, diff) in enumerate(state.patches, start=1):
        entry = name if name.startswith(layout.PATCHES_DIR + "/") else layout.patch_name(index)
        layout.check_entry_name(entry)
        patch_entries.append(entry)
        patch_payloads.append((entry, (diff if diff.endswith("\n") else diff + "\n").encode("utf-8")))

    compatibility = state.behavior_compatibility
    compatibility_text = "null" if compatibility is None else f"{float(compatibility):.4f}"

    manifest: dict[str, Any] = {
        "format": layout.CAPSULE_FORMAT,
        "source": {"repo": state.source_repo, "commit": state.source_commit},
        "genome_ref": layout.GENOME,
        "behavior": {"compatibility": compatibility_text},
        "score": {
            "total": float(score.get("total", 0.0)),
            "components": dict(score.get("components", {})),
        },
        "patches": patch_entries,
        "sbom_digest": sbom_digest,
        "provenance": {
            "evidence": list(state.evidence),
            "llm_traces": [layout.LLM_TRACES] if state.llm_traces else [],
        },
        "status": state.resolved_status(),
    }
    if not manifest["score"]["components"]:
        manifest["score"]["components"] = {
            name: float(score.get(name, 0.0))
            for name in ("runtime", "dependencies", "build", "tests", "behavior", "reproducibility")
        }
    schemas.validate(manifest, "manifest")

    behavior_plan = dict(state.behavior_plan)
    behavior_plan.setdefault("plan_ref", layout.BEHAVIOR_PLAN)
    fingerprints = (
        state.fingerprints
        if state.fingerprints is not None
        else {
            "format": "revive/behavior-fingerprint/v1",
            "plan_ref": layout.BEHAVIOR_PLAN,
            "captured_at": state.created_at,
            "cases": [],
        }
    )

    provenance = {
        "job_id": state.job_id,
        "created_at": state.created_at,
        "redistribute": bool(state.redistributable),
        "sbom_generator": sbom.get("metadata", {}).get("tools", [{}])[0].get("name", "unknown")
        if isinstance(sbom.get("metadata", {}).get("tools"), list) and sbom.get("metadata", {}).get("tools")
        else "provided",
        **state.provenance,
    }
    report = {
        "job_id": state.job_id,
        "status": manifest["status"],
        "score": manifest["score"],
        "behavior_compatibility": compatibility,
        "patches": patch_entries,
        "created_at": state.created_at,
    }

    entries: list[tuple[str, bytes]] = [
        (layout.MANIFEST, _canonical_json(manifest)),
        (layout.GENOME, _canonical_json(state.genome)),
        (layout.ENVIRONMENT, _canonical_json(state.genome)),
        (layout.DEPENDENCIES_LOCK, state.dependencies_lock.encode("utf-8")),
        (layout.DOCKERFILE, state.dockerfile.encode("utf-8")),
        (layout.BEHAVIOR_PLAN, _canonical_json(behavior_plan)),
        (layout.FINGERPRINTS, _canonical_json(fingerprints)),
        (layout.SBOM, sbom_bytes),
        (layout.METADATA_PROVENANCE, _canonical_json(provenance)),
        (layout.PROVENANCE, _canonical_json(provenance)),
        (layout.RESURRECTION_REPORT, _canonical_json(report)),
    ]
    entries.extend(patch_payloads)
    for index, trace in enumerate(state.behavior_traces, start=1):
        entries.append((layout.trace_name(index), trace.encode("utf-8")))
    if state.llm_traces:
        entries.append((layout.LLM_TRACES, ("\n".join(state.llm_traces) + "\n").encode("utf-8")))
    else:
        entries.append((layout.LLM_TRACES, b""))
    if state.source_tree is not None:
        source_tree = Path(state.source_tree)
        if source_tree.is_dir():
            entries.append((layout.SOURCE_TAR, _source_tar(source_tree, _epoch(state.created_at))))

    entries = [
        (
            name,
            _sanitize(payload.decode("utf-8"), root=root, home=home).encode("utf-8") if _is_text(payload) else payload,
        )
        for name, payload in entries
    ]
    _assert_clean(entries, root=None, home=None)
    digests = {
        "algorithm": "sha256",
        "entries": {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(entries)},
    }
    entries.append((layout.DIGESTS, _canonical_json(digests)))
    return entries


def _is_text(payload: bytes) -> bool:
    try:
        payload.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def default_capsule_path(state: RunState, directory: str | Path | None = None) -> Path:
    base = Path(directory) if directory else Path.cwd()
    return base / f"{state.resolved_status()}-{state.job_id or 'run'}{layout.CAPSULE_SUFFIX}"


def build_capsule(state: RunState, out_path: str | Path | None = None, *, verify: bool = True) -> Path:
    """Build the capsule and (by default) self-verify it."""

    entries = build_entries(state)
    payload = _tar_gz(entries, _epoch(state.created_at))
    destination = Path(out_path) if out_path else default_capsule_path(state)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    if verify:
        report = verify_capsule_structure(destination)
        if not report["manifest_ok"] or not report["digests_ok"]:
            raise CapsuleBuildError(f"capsule self-verification failed: {report}")
    return destination


def verify_capsule_structure(path: str | Path) -> dict[str, Any]:
    """Read a capsule back and check manifest schema + every digest."""

    archive_path = Path(path)
    report: dict[str, Any] = {
        "path": str(archive_path),
        "manifest_ok": False,
        "digests_ok": False,
        "missing": [],
        "errors": [],
    }
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members: dict[str, bytes] = {}
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                source = archive.extractfile(member)
                if source is None:
                    continue
                members[member.name] = source.read()
    except (tarfile.TarError, OSError) as exc:
        report["errors"].append(f"cannot read capsule: {exc}")
        return report

    missing = [name for name in layout.REQUIRED_ENTRIES if name not in members]
    report["missing"] = missing
    manifest_bytes = members.get(layout.MANIFEST)
    if manifest_bytes is None:
        report["errors"].append("manifest.json missing")
        return report
    try:
        manifest = json.loads(manifest_bytes)
        schemas.validate(manifest, "manifest")
        report["manifest_ok"] = True
        report["manifest"] = manifest
    except (ValueError, schemas.SchemaError) as exc:
        report["errors"].append(f"manifest invalid: {exc}")
        return report

    digests_bytes = members.get(layout.DIGESTS)
    if digests_bytes is None:
        report["errors"].append("digests.json missing")
        return report
    try:
        digests = json.loads(digests_bytes)
    except ValueError as exc:
        report["errors"].append(f"digests.json invalid: {exc}")
        return report
    expected = digests.get("entries", {})
    bad: list[str] = []
    for name, digest in expected.items():
        payload = members.get(name)
        if payload is None:
            bad.append(f"{name}:missing")
            continue
        actual = hashlib.sha256(payload).hexdigest()
        if actual != digest:
            bad.append(f"{name}:sha256 mismatch")
    for name in members:
        if name != layout.DIGESTS and name not in expected:
            bad.append(f"{name}:not listed in digests.json")
    report["digests_ok"] = not bad
    report["bad_entries"] = bad
    report["ok"] = report["manifest_ok"] and report["digests_ok"] and not missing
    return report


__all__ = [
    "GZIP_LEVEL",
    "CapsuleBuildError",
    "RunState",
    "build_capsule",
    "build_entries",
    "default_capsule_path",
    "generate_sbom",
    "verify_capsule_structure",
]
