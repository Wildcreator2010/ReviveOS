"""Evidence memory store (T-AG-08).

Historical fixes are a compounding asset: (signature, error excerpt, winning
patch) is stored so the repairer can be primed with similar past cases.  Only a
truncated excerpt is ever persisted, never whole private sources, and excerpts
from repositories whose licence is not confirmed are tagged redistribute=false.
The 'swh_case_memory' table itself is created by the T-BE-02 migration; this
module only reads and writes it.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("revive_agents.memory")

MAX_EXCERPT_CHARS = 2048
EMBEDDING_DIMENSIONS = 1536

CASE_MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS swh_case_memory (
    id uuid PRIMARY KEY,
    job_id text NOT NULL,
    signature text NOT NULL,
    excerpt text NOT NULL,
    embedding vector(1536),
    outcome text NOT NULL,
    redistribute boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS swh_case_memory_signature_idx
    ON swh_case_memory (signature);
"""


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump())
    return {"value": str(value)}


def major_signature(signature: Any) -> str:
    """Coarse error family used to reject cross-family retrieval hits."""

    return str(signature or "").split(":", 1)[0].strip()


@dataclass
class Case:
    id: str
    job_id: str
    signature: str
    excerpt: str
    patch: str = ""
    outcome: str = "unknown"
    embedding: list[float] = field(default_factory=list)
    redistribute: bool = False
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "signature": self.signature,
            "excerpt": self.excerpt,
            "patch": self.patch,
            "outcome": self.outcome,
            "embedding": list(self.embedding),
            "redistribute": self.redistribute,
            "created_at": self.created_at,
        }


class MemoryStore:
    """In-process store: the dockerless path and the PG writer's test double."""

    def __init__(self) -> None:
        self.cases: list[Case] = []

    async def save_case(
        self,
        job_id: str,
        error_fact: Any,
        patch: Any,
        outcome: str,
        *,
        embedding: Sequence[float] | None = None,
        redistribute: bool | None = None,
    ) -> Case:
        fact = _as_dict(error_fact)
        excerpt = str(fact.get("excerpt", ""))[:MAX_EXCERPT_CHARS]
        if redistribute is None:
            redistribute = bool(fact.get("license_confirmed", False))
        signature = str(fact.get("signature", ""))
        case = Case(
            id=hashlib.sha256(f"{job_id}|{signature}|{excerpt}".encode()).hexdigest(),
            job_id=str(job_id),
            signature=signature,
            excerpt=excerpt,
            patch=str(patch or ""),
            outcome=str(outcome or "unknown"),
            embedding=[float(x) for x in (embedding or [])],
            redistribute=bool(redistribute),
            created_at=datetime.now(UTC).isoformat(),
        )
        self.cases.append(case)
        if not case.redistribute:
            logger.info(
                "memory_case_saved_non_redistributable",
                extra={"job_id": case.job_id, "signature": case.signature},
            )
        return case

    def all(self) -> list[Case]:
        return list(self.cases)

    def __len__(self) -> int:
        return len(self.cases)

    def clear(self) -> None:
        self.cases.clear()
