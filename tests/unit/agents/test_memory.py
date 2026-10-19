"""T-AG-08: case memory, family filtering and no-embedding degradation."""

from __future__ import annotations

import logging

from revive_agents.memory import (
    CASE_MEMORY_DDL,
    MAX_EXCERPT_CHARS,
    MemoryStore,
    Retriever,
    build_embedder,
    major_signature,
)


class FakeEmbedder:
    def __init__(self, table: dict[str, list[float]]) -> None:
        self.table = table

    async def embed(self, texts):
        return [self.table.get(text, [0.0, 0.0]) for text in texts]


async def test_save_case_truncates_excerpt_and_flags_redistribution():
    store = MemoryStore()
    case = await store.save_case("job-1", {"signature": "R05:x", "excerpt": "x" * 5000}, "diff", "applied")
    assert len(case.excerpt) == MAX_EXCERPT_CHARS
    assert case.redistribute is False
    assert len(store) == 1


async def test_license_confirmed_allows_redistribution():
    store = MemoryStore()
    case = await store.save_case(
        "job-2",
        {"signature": "R01:a", "excerpt": "e", "license_confirmed": True},
        "diff",
        "applied",
    )
    assert case.redistribute is True


async def test_retrieval_filters_by_signature_family_and_ranks():
    store = MemoryStore()
    await store.save_case(
        "job-a",
        {"signature": "R05:a", "excerpt": "mapping", "license_confirmed": True},
        "patch-a",
        "applied",
        embedding=[1.0, 0.0],
    )
    await store.save_case(
        "job-b",
        {"signature": "R05:b", "excerpt": "other", "license_confirmed": True},
        "patch-b",
        "applied",
        embedding=[0.0, 1.0],
    )
    await store.save_case(
        "job-c",
        {"signature": "R01:c", "excerpt": "wrong family", "license_confirmed": True},
        "patch-c",
        "applied",
        embedding=[1.0, 0.0],
    )
    retriever = Retriever(store, FakeEmbedder({"query text": [1.0, 0.0]}))
    hits = await retriever.similar({"signature": "R05:query", "excerpt": "query text"}, k=3)

    assert [hit.job_id for hit in hits] == ["job-a", "job-b"]
    assert all(major_signature(hit.signature) == "R05" for hit in hits)


async def test_missing_embedder_degrades_to_empty(caplog):
    store = MemoryStore()
    await store.save_case("job-a", {"signature": "R05:a", "excerpt": "e"}, "diff", "applied", embedding=[1.0])
    retriever = Retriever(store, None)
    assert retriever.degraded is True

    with caplog.at_level(logging.INFO, logger="revive_agents.memory"):
        hits = await retriever.similar({"signature": "R05:a", "excerpt": "e"})
    assert hits == []
    assert any("memory_retrieval_degraded" in record.getMessage() for record in caplog.records)


def test_build_embedder_degrades_without_config():
    assert build_embedder() is None


def test_case_memory_ddl_uses_pgvector_1536():
    assert "swh_case_memory" in CASE_MEMORY_DDL
    assert "vector(1536)" in CASE_MEMORY_DDL
