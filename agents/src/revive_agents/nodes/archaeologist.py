"""Archaeologist node (T-AG-03): evidence-bound genome reinforcement.

When the core engine reports overall_confidence below 0.7 the LLM reads the
injected evidence corpus (README/issue excerpts/Dockerfile text) and may raise
confidence or append evidence.  Every modification must cite an existing
evidence id: a reference to an unknown id is a hallucination and is dropped
with a warning.  Unparseable structured output leaves the input genome
untouched.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..llm.base import BudgetExceeded, LLMError, LLMOutputError
from ..prompts import render

GENOME_FIELDS = {
    "python",
    "os",
    "dependencies",
    "cuda",
    "system_libs",
    "overall_confidence",
}
_VALID_SOURCE_KINDS = {
    "git_history",
    "manifest_file",
    "ci_config",
    "doc",
    "release_artifact",
    "inference",
}

RESPONSE_FORMAT: dict[str, Any] = {
    "title": "archaeologist-updates",
    "type": "object",
    "properties": {
        "updates": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "confidence": {"type": "number"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "version": {"type": ["string", "null"]},
                    "image": {"type": ["string", "null"]},
                    "llm_reason": {"type": "string"},
                },
            },
        }
    },
    "required": ["updates"],
}


@dataclass
class ArchaeologistOutcome:
    genome: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    modifications: list[dict[str, Any]] = field(default_factory=list)

    def __iter__(self) -> Iterable[Any]:
        # Allows 'genome, warnings = archaeologist(...)' as well as attribute use.
        yield self.genome
        yield self.warnings


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump())
    return {"value": str(value)}


def _evidence_id(item: Any) -> str:
    data = _as_dict(item)
    return str(data.get("id") or data.get("reference") or "")


def _evidence_view(item: Any) -> dict[str, Any]:
    data = _as_dict(item)
    kind = str(data.get("source_kind") or "inference")
    if kind not in _VALID_SOURCE_KINDS:
        kind = "inference"
    return {
        "id": _evidence_id(item),
        "source_kind": kind,
        "reference": str(data.get("reference") or data.get("id") or ""),
        "note": str(data.get("note") or "")[:500],
    }


def _evidence_record(item: Any, reason: str) -> dict[str, Any]:
    view = _evidence_view(item)
    note_parts = [view["note"], f"llm_reason: {reason}"]
    record: dict[str, Any] = {
        "source_kind": view["source_kind"],
        "reference": view["reference"],
    }
    joined = " | ".join(part for part in note_parts if part)
    if joined:
        record["note"] = joined[:1000]
    return record


def _corpus_index(evidence_corpus: Iterable[Any]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for item in evidence_corpus or []:
        identifier = _evidence_id(item)
        if identifier:
            index[identifier] = item
    return index


async def archaeologist(
    genome: Any,
    low_confidence_fields: Sequence[str],
    evidence_corpus: Sequence[Any],
    provider: Any,
    *,
    job_id: str = "",
) -> ArchaeologistOutcome:
    original = copy.deepcopy(_as_dict(genome))
    index = _corpus_index(evidence_corpus)
    evidence_json = json.dumps(
        [_evidence_view(item) for item in evidence_corpus or []],
        ensure_ascii=False,
        sort_keys=True,
    )
    messages = render(
        "archaeologist",
        fields=", ".join(str(field_name) for field_name in low_confidence_fields),
        evidence=evidence_json,
    )
    try:
        completion = await provider.complete(messages, response_format=RESPONSE_FORMAT)
        payload = completion.json
    except BudgetExceeded:
        raise
    except LLMOutputError as exc:
        return ArchaeologistOutcome(
            copy.deepcopy(original),
            [f"llm structured output failed; original genome retained: {exc}"],
            [],
        )
    except LLMError as exc:
        return ArchaeologistOutcome(
            copy.deepcopy(original),
            [f"llm call failed; original genome retained: {exc}"],
            [],
        )
    if not isinstance(payload, dict):
        return ArchaeologistOutcome(copy.deepcopy(original), ["llm payload was not an object"], [])
    updates = payload.get("updates")
    if not isinstance(updates, dict):
        return ArchaeologistOutcome(copy.deepcopy(original), ["llm payload had no updates object"], [])

    result = copy.deepcopy(original)
    warnings: list[str] = []
    modifications: list[dict[str, Any]] = []
    for raw_name, change in updates.items():
        name = str(raw_name)
        if name not in GENOME_FIELDS:
            warnings.append(f"rejected unknown genome field {name!r}")
            continue
        if not isinstance(change, dict):
            warnings.append(f"rejected malformed update for {name}")
            continue
        refs = [str(ref) for ref in (change.get("evidence_ids") or [])]
        if not refs:
            warnings.append(f"rejected update for {name}: no evidence ids cited")
            continue
        unknown = sorted({ref for ref in refs if ref not in index})
        if unknown:
            warnings.append(f"rejected hallucinated evidence for {name}: {', '.join(unknown)}")
            continue
        reason = str(change.get("llm_reason") or "").strip()
        if not reason:
            warnings.append(f"rejected update for {name}: missing llm_reason")
            continue
        confidence = float(change.get("confidence") or 0.0)
        if name == "overall_confidence":
            result[name] = max(float(result.get(name) or 0.0), confidence)
            modifications.append(
                {
                    "field": name,
                    "confidence": result[name],
                    "evidence_ids": refs,
                    "llm_reason": reason,
                }
            )
            continue
        target = result.get(name)
        if not isinstance(target, dict):
            warnings.append(f"rejected update for {name}: unsupported field shape")
            continue
        updated = dict(target)
        updated["confidence"] = max(float(updated.get("confidence") or 0.0), confidence)
        if change.get("version"):
            updated["version"] = str(change["version"])
        if change.get("image"):
            updated["image"] = str(change["image"])
        existing = list(updated.get("evidence") or [])
        for ref in refs:
            existing.append(_evidence_record(index[ref], reason))
        updated["evidence"] = existing
        result[name] = updated
        modifications.append(
            {
                "field": name,
                "confidence": updated["confidence"],
                "evidence_ids": refs,
                "llm_reason": reason,
            }
        )
    return ArchaeologistOutcome(result, warnings, modifications)
