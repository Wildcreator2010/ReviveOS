"""Archaeology artifact persistence and evidence retrieval (T-BE-09).

Two red lines shape this module.  The excerpt *text* is never stored and never
returned -- only its sha256 -- and an unconfigured embedding endpoint must never
turn into a failed insert: the vector stays NULL, retrieval degrades to confidence
ordering, and the skip is logged at info level.
"""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)

GENOME_SECTIONS = ("python", "os", "cuda")


class EmbedClient(Protocol):
    """The slice of httpx.AsyncClient this module needs, so tests can inject a fake."""

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any: ...


@dataclass(frozen=True)
class EmbedConfig:
    base_url: str
    model: str
    api_key: str = ""

    @classmethod
    def from_env(cls) -> EmbedConfig | None:
        """Read `REVIVE_LLM__EMBED_*`; None means embeddings are simply off."""

        base_url = os.getenv("REVIVE_LLM__EMBED__BASE_URL", "").strip()
        model = os.getenv("REVIVE_LLM__EMBED__MODEL", "").strip()
        if not base_url or not model:
            return None
        return cls(base_url=base_url, model=model, api_key=os.getenv("REVIVE_LLM__EMBED__API_KEY", "").strip())


async def embed_excerpt(text: str, config: EmbedConfig | None, client: EmbedClient | None = None) -> list[float] | None:
    """Return a vector for the excerpt, or None when embeddings are not configured."""

    if config is None:
        log.info("evidence.embed_unconfigured", chars=len(text))
        return None
    if not text.strip():
        return None
    if client is not None:
        return await _fetch_vector(client, config, text)

    import httpx

    async with httpx.AsyncClient(timeout=30) as owned_client:
        return await _fetch_vector(owned_client, config, text)


async def _fetch_vector(client: EmbedClient, config: EmbedConfig, text: str) -> list[float]:
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    response = await client.post(
        f"{config.base_url.rstrip('/')}/embeddings",
        json={"model": config.model, "input": text},
        headers=headers,
    )
    response.raise_for_status()
    data = response.json()["data"][0]["embedding"]
    if not isinstance(data, list) or not all(isinstance(value, (int, float)) for value in data):
        raise ValueError("embedding response is not a numeric vector")
    return [float(value) for value in data]


def excerpt_digest(text: str | None) -> str | None:
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def confidence_by_reference(genome: Mapping[str, Any]) -> dict[str, float]:
    """Evidence inherits the confidence of the inference section that cited it."""

    scores: dict[str, float] = {}
    for section in GENOME_SECTIONS:
        block = genome.get(section)
        if not isinstance(block, dict):
            continue
        try:
            confidence = float(block.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        for item in block.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            reference = str(item.get("reference", ""))
            if reference:
                scores[reference] = max(scores.get(reference, 0.0), confidence)
    overall = genome.get("overall_confidence")
    if isinstance(overall, (int, float)):
        for reference in list(scores):
            scores[reference] = max(scores[reference], float(overall))
    return scores


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = int(base64.urlsafe_b64decode(cursor.encode() + b"=" * (-len(cursor) % 4)).decode())
    except (ValueError, UnicodeDecodeError):
        raise ValueError("invalid cursor") from None
    if value < 0:
        raise ValueError("invalid cursor")
    return value


def public_evidence(record: Any) -> dict[str, Any]:
    """Response-safe projection: metadata and the digest, never the excerpt text."""

    return {
        "id": record.id,
        "project_id": record.project_id,
        "source_kind": record.source_kind,
        "reference": record.reference,
        "facts": dict(record.facts or {}),
        "confidence": float(record.confidence),
        "excerpt_hash": record.excerpt_hash,
        "created_at": record.created_at,
    }


async def persist_evidence(
    repository: Any,
    *,
    project_id: str,
    job_id: str | None,
    genome: Mapping[str, Any],
    items: Sequence[Any],
    embedder: Callable[[str], Any] | None = None,
) -> int:
    """Write one evidence row per archaeology item; excerpt text is only hashed."""

    scores = confidence_by_reference(genome)
    written = 0
    for item in items:
        ref_string = getattr(item, "ref_string", None)
        reference = ref_string() if callable(ref_string) else str(getattr(item, "reference", item))
        facts = dict(getattr(item, "facts", {}) or {})
        note = getattr(item, "note", None)
        if note and "note" not in facts:
            facts["note"] = str(note)
        excerpt = facts.get("excerpt")
        text = str(excerpt) if isinstance(excerpt, str) else None
        vector = None
        if text:
            vector = await embedder(text) if embedder is not None else None
            facts = {key: value for key, value in facts.items() if key != "excerpt"}
        await repository.add_evidence(
            project_id,
            str(getattr(item, "source_kind", "inference")),
            reference,
            facts,
            scores.get(reference, 0.0),
            text,
            job_id,
            vector,
        )
        written += 1
    return written


def build_attempt_rows(emitted: Sequence[Mapping[str, Any]], *, attempts: int, build_ok: bool) -> list[dict[str, Any]]:
    """Reconstruct one row per build try from the emitted build.* events."""

    reasons: dict[int, str] = {}
    for event in emitted:
        if event.get("type") != "build.failed":
            continue
        payload = event.get("payload") or {}
        try:
            attempt = int(payload.get("attempt", 0))
        except (TypeError, ValueError):
            continue
        if attempt:
            reasons[attempt] = str(payload.get("reason", ""))
    return [
        {
            "attempt": attempt,
            "ok": attempt == attempts and build_ok,
            "exit_code": None,
            "error_fact": {} if attempt == attempts and build_ok else {"reason": reasons.get(attempt, "")},
        }
        for attempt in range(1, max(attempts, 0) + 1)
    ]


def patch_rows(patches: Sequence[Any], emitted: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pair each proposal with the repair.applied event that decided it."""

    applied: list[bool] = []
    for event in emitted:
        if event.get("type") != "repair.applied":
            continue
        payload = event.get("payload") or {}
        applied.append(bool(payload.get("applied")))

    rows: list[dict[str, Any]] = []
    for index, patch in enumerate(patches):
        data = patch if isinstance(patch, Mapping) else {"diff": str(patch)}
        files = data.get("touched_files") or []
        rows.append(
            {
                "entry": str(files[0]) if files else f"patches/{index + 1}.patch",
                "diff": str(data.get("diff", "")),
                "accepted": applied[index] if index < len(applied) else bool(files),
                "files_changed": len(files),
                "lines_changed": int(data.get("lines_added", 0) or 0) + int(data.get("lines_removed", 0) or 0),
            }
        )
    return rows


async def persist_job_artifacts(
    repository: Any,
    *,
    project_id: str,
    job_id: str,
    genome: Mapping[str, Any],
    emitted: Sequence[Mapping[str, Any]],
    state: Any,
    build_ok: bool,
) -> dict[str, int]:
    """Write genome/build/patch/behavior/fingerprint rows for one finished job."""

    counts = {"genomes": 0, "builds": 0, "patches": 0, "behavior": 0, "fingerprints": 0}
    if hasattr(repository, "add_genome"):
        await repository.add_genome(project_id, dict(genome), job_id=job_id)
        counts["genomes"] = 1

    attempts = int(getattr(state, "build_attempts", 0) or 0)
    if hasattr(repository, "add_build_attempt"):
        for row in build_attempt_rows(emitted, attempts=attempts, build_ok=build_ok):
            await repository.add_build_attempt(
                job_id, row["attempt"], ok=row["ok"], exit_code=row["exit_code"], error_fact=row["error_fact"]
            )
            counts["builds"] += 1

    if hasattr(repository, "add_patch"):
        for row in patch_rows(list(getattr(state, "patches", []) or []), emitted):
            await repository.add_patch(
                job_id,
                row["entry"],
                row["diff"],
                accepted=row["accepted"],
                files_changed=row["files_changed"],
                lines_changed=row["lines_changed"],
            )
            counts["patches"] += 1

    cases = 0
    plan_ref = None
    for event in emitted:
        if event.get("type") == "behavior.captured":
            cases = int((event.get("payload") or {}).get("cases", 0) or 0)
    plan = getattr(state, "behavior_plan", None)
    if isinstance(plan, Mapping):
        plan_ref = plan.get("plan_ref")
    if hasattr(repository, "add_behavior_run"):
        await repository.add_behavior_run(
            job_id,
            plan_ref=str(plan_ref) if plan_ref else None,
            cases=cases,
            compatibility=getattr(state, "behavior_compatibility", None),
            payload=dict(plan) if isinstance(plan, Mapping) else {},
        )
        counts["behavior"] = 1

    fingerprints = getattr(state, "fingerprints", None)
    if fingerprints and hasattr(repository, "add_fingerprint"):
        await repository.add_fingerprint(
            project_id, fingerprints if isinstance(fingerprints, dict) else {"value": str(fingerprints)}, job_id
        )
        counts["fingerprints"] = 1
    return counts


async def evidence_page(
    repository: Any,
    project_id: str,
    *,
    source_kind: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Confidence-ordered page with an opaque offset cursor (same shape as the REST list)."""

    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    offset = decode_cursor(cursor)
    rows = await repository.list_evidence(project_id, source_kind, limit=limit + 1, offset=offset)
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [public_evidence(record) for record in page],
        "next_cursor": encode_cursor(offset + limit) if has_more else None,
    }


__all__ = [
    "EmbedConfig",
    "build_attempt_rows",
    "confidence_by_reference",
    "decode_cursor",
    "embed_excerpt",
    "encode_cursor",
    "evidence_page",
    "excerpt_digest",
    "patch_rows",
    "persist_evidence",
    "persist_job_artifacts",
    "public_evidence",
]
