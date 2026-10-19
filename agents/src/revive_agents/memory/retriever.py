"""Top-k similar-case retrieval (T-AG-08).

The repair main chain must never depend on the memory store: when no embedding
provider is configured (REVIVE_LLM__EMBED__MODEL unset) 'similar' degrades to
an empty result and logs at info level.  Hits whose coarse signature family
differs from the query are always filtered out.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Any, Protocol

from .store import Case, MemoryStore, major_signature

logger = logging.getLogger("revive_agents.memory")


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump())
    return {"value": str(value)}


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class Retriever:
    def __init__(self, store: MemoryStore, embedder: Embedder | None = None) -> None:
        self.store = store
        self.embedder = embedder

    @property
    def degraded(self) -> bool:
        return self.embedder is None

    async def similar(self, error_fact: Any, k: int = 3) -> list[Case]:
        if self.embedder is None:
            logger.info(
                "memory_retrieval_degraded",
                extra={"reason": "no embedding provider configured"},
            )
            return []
        fact = _as_dict(error_fact)
        query_major = major_signature(fact.get("signature", ""))
        candidates = [case for case in self.store.all() if major_signature(case.signature) == query_major]
        if not candidates:
            return []
        text = str(fact.get("excerpt", "")) or query_major
        vectors = await self.embedder.embed([text])
        if not vectors:
            return []
        query_vector = vectors[0]
        scored: list[tuple[float, Case]] = []
        for case in candidates:
            if not case.embedding:
                continue
            scored.append((cosine_similarity(query_vector, case.embedding), case))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [case for _, case in scored[: max(int(k), 0)]]


class OpenAIEmbedder:
    """OpenAI-compatible embeddings client used when REVIVE_LLM__EMBED__* is set."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        *,
        client: Any = None,
        sleep: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("REVIVE_LLM__EMBED__API_KEY is required for the embedding provider")
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._client = client
        self._sleep = sleep

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        import httpx

        from ..llm._http import post_json

        payload = {"model": self.model, "input": list(texts)}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/embeddings"

        async def _send(client: Any) -> dict[str, Any]:
            return await post_json(
                client,
                url,
                headers=headers,
                payload=payload,
                sleep=self._sleep,
                error_prefix="embedding request",
            )

        if self._client is not None:
            body = await _send(self._client)
        else:
            async with httpx.AsyncClient() as client:
                body = await _send(client)
        rows = sorted(body.get("data") or [], key=lambda row: row.get("index", 0))
        return [[float(x) for x in (row.get("embedding") or [])] for row in rows]


def build_embedder(config: Any = None) -> Embedder | None:
    """Return an embedder, or None so callers degrade to empty retrieval."""

    from ..llm.factory import ConfigSource

    source = ConfigSource(config)
    model = source.get("LLM_EMBED__MODEL") or source.get("LLM_EMBED_MODEL")
    if not model:
        logger.info(
            "memory_embedder_absent",
            extra={"reason": "REVIVE_LLM__EMBED__MODEL is not configured"},
        )
        return None
    api_key = source.get("LLM_EMBED__API_KEY") or source.get("LLM_EMBED_API_KEY")
    base_url = source.get("LLM_EMBED__BASE_URL") or source.get("LLM_EMBED_BASE_URL")
    return OpenAIEmbedder(api_key, str(model), str(base_url) if base_url else None)
