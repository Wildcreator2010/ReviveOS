"""Repair agent (T-AG-04): the only node allowed to propose target-code changes.

The node only ever emits a PatchProposal.  A proposal is returned only after it
passes, in order: the 5/10/300 permission ceiling, unified-diff parsing, the
workspace-manifest whitelist, the dependency-pin guard, 'ast.parse' for every
touched Python file, and finally 'git apply --check' against a scratch copy of
the manifest (or an injected fixture workspace).  Two consecutive failures with
the same signature return GiveUp so the supervisor can prune the branch.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import revive_core.gitutil as core_git

from ..diffutil import (
    DiffError,
    apply_file_patch,
    count_changes,
    parse_unified_diff,
    touched_paths,
)
from ..limits import MAX_FILES, MAX_ITERATIONS, MAX_LINES
from ..llm.base import BudgetExceeded, LLMOutputError
from ..prompts import render

GIT_ENV_VAR = "REVIVE_GIT_BIN"
_RISK_LEVELS = ("low", "medium", "high")
_DEP_FILE_NAMES = {
    "requirements.txt",
    "requirements-dev.txt",
    "constraints.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "pipfile",
    "poetry.lock",
    "environment.yml",
    "environment.yaml",
}
_DEP_VERSION_RE = re.compile(r"[A-Za-z0-9_.\-\[\]]+\s*(?:==|>=|<=|~=|!=|>|<)\s*[0-9]")


class GitUnavailable(core_git.GitUnavailableError):
    """No usable git executable was found (T-AG-04 requires one for --check)."""


@dataclass(frozen=True)
class PatchProposal:
    diff: str
    rationale: str
    touched_files: list[str]
    lines_added: int
    lines_removed: int
    risk: str
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "diff": self.diff,
            "rationale": self.rationale,
            "touched_files": list(self.touched_files),
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "risk": self.risk,
            "signature": self.signature,
        }


@dataclass(frozen=True)
class Refused:
    reason: str
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"refused": self.reason, "signature": self.signature}


@dataclass(frozen=True)
class GiveUp:
    reason: str
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"give_up": self.reason, "signature": self.signature}


# --------------------------------------------------------------------------- git
# The canonical resolver lives in revive_core.gitutil so the whole monorepo
# shares one REVIVE_GIT_BIN contract; this layer only adapts the raise into a
# boolean probe for tests and callers that want to skip gracefully.
def find_git(repo_root: str | Path | None = None) -> str | None:
    try:
        return core_git.find_git()
    except core_git.GitUnavailableError:
        return None


def require_git(repo_root: str | Path | None = None) -> str:
    try:
        return core_git.find_git()
    except core_git.GitUnavailableError as exc:
        raise GitUnavailable(str(exc)) from exc


def git_available(repo_root: str | Path | None = None) -> bool:
    return find_git(repo_root) is not None


# ------------------------------------------------------------------- manifest
def _normalize_path(path: str) -> str:
    value = str(path).replace("\\", "/").lstrip("/")
    if value.startswith("./"):
        value = value[2:]
    return value


def _manifest_entries(manifest: Any) -> list[dict[str, Any]]:
    if manifest is None:
        return []
    if isinstance(manifest, dict):
        entries: list[dict[str, Any]] = []
        for path, meta in manifest.items():
            if isinstance(meta, dict):
                entry = {"path": path}
                entry.update(meta)
                entries.append(entry)
            else:
                entries.append({"path": path, "content": meta})
        return entries
    return [dict(entry) for entry in manifest]


def _entry_content(entry: dict[str, Any]) -> str:
    for key in ("content", "text"):
        value = entry.get(key)
        if isinstance(value, str):
            return value
    lines = entry.get("lines")
    if isinstance(lines, str):
        return lines
    if isinstance(lines, list):
        return "\n".join(str(line) for line in lines) + ("\n" if lines else "")
    return ""


def manifest_content_map(manifest: Any) -> dict[str, str]:
    return {_normalize_path(e.get("path", "")): _entry_content(e) for e in _manifest_entries(manifest)}


def _materialize(manifest_map: dict[str, str], root: Path) -> None:
    for path, content in manifest_map.items():
        if not path or path.startswith("../") or Path(path).is_absolute():
            continue
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _git_apply_check(
    diff: str,
    manifest_map: dict[str, str],
    *,
    workspace: str | Path | None,
    git_bin: str | None,
    runner: Callable[..., Any] | None,
    scratch_dir: str | Path | None = None,
) -> None:
    git = git_bin or require_git()
    runner = runner or subprocess.run
    created: str | None = None
    try:
        if workspace is None:
            base = Path(scratch_dir) if scratch_dir else None
            if base is not None:
                base.mkdir(parents=True, exist_ok=True)
            created = tempfile.mkdtemp(prefix="revive-git-check-", dir=str(base) if base else None)
            target = Path(created)
            _materialize(manifest_map, target)
        else:
            target = Path(workspace)
            if not target.is_dir():
                raise GitUnavailable(f"workspace {target} is not a directory")
        proc = runner(
            [git, "apply", "--check", "--whitespace=nowarn", "-p1", "-"],
            input=diff,
            text=True,
            capture_output=True,
            cwd=str(target),
            timeout=30,
        )
        if getattr(proc, "returncode", 1) != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:400]
            raise ValueError(f"git apply --check failed: {detail}")
    finally:
        if created is not None:
            shutil.rmtree(created, ignore_errors=True)


# ----------------------------------------------------------------- validation
def validate_proposal(
    proposal: PatchProposal,
    workspace_manifest: Any,
    *,
    workspace: str | Path | None = None,
    git_bin: str | None = None,
    check_git: bool = True,
    runner: Callable[..., Any] | None = None,
    scratch_dir: str | Path | None = None,
) -> Refused | None:
    """Return a Refused reason, or None when the proposal is acceptable."""

    manifest_map = manifest_content_map(workspace_manifest)
    try:
        patches = parse_unified_diff(proposal.diff)
    except DiffError as exc:
        return Refused(f"invalid unified diff: {exc}", proposal.signature)
    derived = touched_paths(patches)
    declared = sorted(_normalize_path(p) for p in proposal.touched_files)
    if declared and declared != sorted(derived):
        return Refused("touched_files disagrees with the diff", proposal.signature)
    effective_files = sorted(set(derived) | set(declared))
    if len(effective_files) > MAX_FILES:
        return Refused(
            f"patch touches {len(effective_files)} files; the maximum is {MAX_FILES}",
            proposal.signature,
        )
    added, removed = count_changes(patches)
    if added + removed > MAX_LINES:
        return Refused(
            f"patch changes {added + removed} lines; the maximum is {MAX_LINES}",
            proposal.signature,
        )
    outside = [p for p in derived if p not in manifest_map]
    if outside:
        return Refused(
            "patch touches files outside the workspace manifest: " + ", ".join(outside),
            proposal.signature,
        )
    for path in derived:
        if Path(path).name.lower() in _DEP_FILE_NAMES:
            removed_lines: set[str] = set()
            added_lines: set[str] = set()
            for patch in patches:
                if patch.path != path:
                    continue
                for hunk in patch.hunks:
                    for tag, text in hunk.lines:
                        stripped = text.strip()
                        if tag == "-":
                            removed_lines.add(stripped)
                        elif tag == "+":
                            added_lines.add(stripped)
            for text in sorted(added_lines - removed_lines):
                if _DEP_VERSION_RE.search(text):
                    return Refused(
                        f"dependency version changes are not allowed in {path}: {text!r}",
                        proposal.signature,
                    )
        if path.endswith(".py"):
            patch = next(p for p in patches if p.path == path)
            try:
                updated = apply_file_patch(manifest_map[path], patch)
            except DiffError as exc:
                return Refused(f"patch does not apply to {path}: {exc}", proposal.signature)
            try:
                ast.parse(updated, filename=path)
            except SyntaxError as exc:
                return Refused(
                    f"python syntax error in {path}: {exc.msg} (line {exc.lineno})",
                    proposal.signature,
                )
    if check_git:
        try:
            _git_apply_check(
                proposal.diff,
                manifest_map,
                workspace=workspace,
                git_bin=git_bin,
                runner=runner,
                scratch_dir=scratch_dir,
            )
        except ValueError as exc:
            return Refused(str(exc), proposal.signature)
    return None


# --------------------------------------------------------------------- prompt
def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump())
    return {"value": str(value)}


def _fact_signature(error_fact: Any) -> str:
    fact = _as_dict(error_fact)
    return str(fact.get("signature", ""))


def _attempt_signature(attempt: Any) -> str:
    return str(_as_dict(attempt).get("signature", ""))


def _attempt_accepted(attempt: Any) -> bool:
    return bool(_as_dict(attempt).get("accepted", False))


def _consecutive_same_signature_failures(attempts: Sequence[Any], signature: str) -> bool:
    if len(attempts) < 2:
        return False
    recent = attempts[-2:]
    return all(_attempt_signature(a) == signature and not _attempt_accepted(a) for a in recent)


def _render_manifest(manifest: Any) -> str:
    entries = []
    for entry in _manifest_entries(manifest):
        entries.append(
            {
                "path": _normalize_path(entry.get("path", "")),
                "sha256": entry.get("sha256", ""),
                "lines": entry.get("lines", ""),
                "content": _entry_content(entry),
            }
        )
    return json.dumps(entries, ensure_ascii=False, sort_keys=True)


def _render_memory(memory_cases: Any) -> str:
    cases = []
    for case in memory_cases or []:
        data = _as_dict(case)
        cases.append(
            {
                "signature": data.get("signature", ""),
                "excerpt": str(data.get("excerpt", ""))[:512],
                "outcome": data.get("outcome", ""),
                "patch": str(data.get("patch", ""))[:2048],
            }
        )
    return json.dumps(cases, ensure_ascii=False, sort_keys=True)


# ----------------------------------------------------------------------- node
async def repair(
    error_fact: Any,
    workspace_manifest: Any,
    prior_attempts: Sequence[Any],
    provider: Any,
    *,
    workspace: str | Path | None = None,
    git_bin: str | None = None,
    check_git: bool = True,
    memory_cases: Any = None,
    job_id: str = "",
    runner: Callable[..., Any] | None = None,
    scratch_dir: str | Path | None = None,
) -> PatchProposal | Refused | GiveUp:
    signature = _fact_signature(error_fact)
    attempts = list(prior_attempts or [])
    if len(attempts) >= MAX_ITERATIONS:
        return GiveUp(
            reason=f"repair iteration budget exhausted ({MAX_ITERATIONS})",
            signature=signature,
        )
    if _consecutive_same_signature_failures(attempts, signature):
        return GiveUp(
            reason=f"two consecutive failed attempts with signature {signature!r}",
            signature=signature,
        )
    fact = _as_dict(error_fact)
    messages = render(
        "repairer",
        error_fact=json.dumps(fact, ensure_ascii=False, sort_keys=True),
        manifest=_render_manifest(workspace_manifest),
        prior_attempts=json.dumps([_as_dict(a) for a in attempts], ensure_ascii=False, sort_keys=True),
        memory_cases=_render_memory(memory_cases),
    )
    response_format = {
        "title": "patch-proposal",
        "type": "object",
        "properties": {
            "diff": {"type": "string"},
            "rationale": {"type": "string"},
            "touched_files": {"type": "array", "items": {"type": "string"}},
            "lines_added": {"type": "integer"},
            "lines_removed": {"type": "integer"},
            "risk": {"enum": ["low", "medium", "high"]},
        },
        "required": ["diff", "rationale", "touched_files", "risk"],
    }
    try:
        completion = await provider.complete(messages, response_format=response_format)
    except BudgetExceeded:
        raise
    except LLMOutputError as exc:
        return Refused(f"structured output rejected: {exc}", signature)
    payload = getattr(completion, "json", None) or {}
    if not isinstance(payload, dict) or not payload:
        return Refused("llm returned no JSON object", signature)
    risk = str(payload.get("risk", "")).strip().lower()
    if risk not in _RISK_LEVELS:
        return Refused(f"risk must be one of {_RISK_LEVELS}, got {risk!r}", signature)
    diff = str(payload.get("diff", ""))
    try:
        patches = parse_unified_diff(diff)
    except DiffError as exc:
        return Refused(f"invalid unified diff: {exc}", signature)
    derived = touched_paths(patches)
    declared = [_normalize_path(str(p)) for p in payload.get("touched_files") or []]
    if declared and sorted(declared) != sorted(derived):
        return Refused("touched_files disagrees with the diff", signature)
    added, removed = count_changes(patches)
    proposal = PatchProposal(
        diff=diff,
        rationale=str(payload.get("rationale", "")),
        touched_files=derived,
        lines_added=added,
        lines_removed=removed,
        risk=risk,
        signature=signature,
    )
    refusal = validate_proposal(
        proposal,
        workspace_manifest,
        workspace=workspace,
        git_bin=git_bin,
        check_git=check_git,
        runner=runner,
        scratch_dir=scratch_dir,
    )
    return refusal or proposal
