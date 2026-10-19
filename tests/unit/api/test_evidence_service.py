"""T-BE-09 service rules that must hold without a database."""

from __future__ import annotations

from typing import Any

import pytest
from revive_api.services import evidence_service as svc
from revive_core.archaeology import EvidenceItem, EvidenceReference


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeEmbedClient:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        self.calls.append((url, json, headers))
        return FakeResponse({"data": [{"embedding": self.vector}]})


class RejectingClient:
    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        return FakeResponse({"data": [{"embedding": "not-a-vector"}]})


def test_embed_config_is_off_without_both_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("REVIVE_LLM__EMBED__BASE_URL", "REVIVE_LLM__EMBED__MODEL", "REVIVE_LLM__EMBED__API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert svc.EmbedConfig.from_env() is None

    monkeypatch.setenv("REVIVE_LLM__EMBED__MODEL", "text-embedding-3-small")
    assert svc.EmbedConfig.from_env() is None

    monkeypatch.setenv("REVIVE_LLM__EMBED__BASE_URL", "https://embed.internal/v1")
    config = svc.EmbedConfig.from_env()
    assert config is not None and config.model == "text-embedding-3-small"


async def test_unconfigured_embedding_skips_instead_of_failing() -> None:
    assert await svc.embed_excerpt("setup.py needs numpy==1.16", None) is None


async def test_configured_embedding_calls_the_openai_compatible_endpoint() -> None:
    client = FakeEmbedClient([0.1, 0.2, 0.3])
    config = svc.EmbedConfig(base_url="https://embed.internal/v1/", model="bge-m3", api_key="k-1")

    vector = await svc.embed_excerpt("flask==1.1.4", config, client)

    assert vector == [0.1, 0.2, 0.3]
    url, payload, headers = client.calls[0]
    assert url == "https://embed.internal/v1/embeddings"
    assert payload == {"model": "bge-m3", "input": "flask==1.1.4"}
    assert headers["Authorization"] == "Bearer k-1"


async def test_blank_excerpt_never_hits_the_embedder() -> None:
    client = FakeEmbedClient([0.0])
    assert await svc.embed_excerpt("   ", svc.EmbedConfig(base_url="https://e/v1", model="m"), client) is None
    assert client.calls == []


async def test_malformed_embedding_response_is_rejected() -> None:
    with pytest.raises(ValueError):
        await svc.embed_excerpt(
            "text",
            svc.EmbedConfig(base_url="https://e/v1", model="m"),
            RejectingClient(),  # type: ignore[arg-type]
        )


def test_confidence_is_inherited_from_the_citing_section() -> None:
    genome = {
        "python": {"confidence": 0.9, "evidence": [{"reference": "pyproject.toml", "source_kind": "manifest_file"}]},
        "os": {"confidence": 0.4, "evidence": [{"reference": "Dockerfile", "source_kind": "manifest_file"}]},
        "cuda": {"confidence": 0.0, "evidence": []},
        "overall_confidence": 0.62,
    }

    scores = svc.confidence_by_reference(genome)

    assert scores["pyproject.toml"] == pytest.approx(0.9)
    assert scores["Dockerfile"] == pytest.approx(0.62)
    assert set(scores) == {"pyproject.toml", "Dockerfile"}


def _item(file: str, facts: dict[str, Any], note: str | None = None) -> EvidenceItem:
    return EvidenceItem(
        source_kind="manifest_file", reference=EvidenceReference(file=file, commit_sha="abc123"), facts=facts, note=note
    )


class RecordingRepo:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict[str, Any], float, str | None, str | None, list[float] | None]] = []

    async def add_evidence(
        self,
        project_id: str,
        source_kind: str,
        reference: str,
        facts: dict[str, Any],
        confidence: float = 0.0,
        excerpt: str | None = None,
        job_id: str | None = None,
        excerpt_embedding: list[float] | None = None,
    ) -> None:
        self.rows.append((source_kind, reference, facts, confidence, excerpt, job_id, excerpt_embedding))


async def test_persist_evidence_hashes_excerpt_and_never_stores_the_text() -> None:
    repo = RecordingRepo()
    secret = "SECRET-TOKEN sqlite:///top-secret"
    items = [_item("requirements.txt", {"dependencies": ["flask==1.1.4"], "excerpt": secret}, "pinned")]
    genome = {"python": {"confidence": 0.8, "evidence": [{"reference": "requirements.txt@abc123"}]}}

    written = await svc.persist_evidence(
        repo, project_id="prj_1", job_id="job_1", genome=genome, items=items, embedder=None
    )

    assert written == 1
    source_kind, reference, facts, confidence, excerpt, job_id, vector = repo.rows[0]
    assert source_kind == "manifest_file"
    assert reference == "requirements.txt@abc123"
    assert "excerpt" not in facts
    assert facts["note"] == "pinned"
    assert confidence == pytest.approx(0.8)
    assert excerpt == secret
    assert job_id == "job_1"
    assert vector is None


async def test_persist_evidence_embeds_only_when_an_embedder_is_given() -> None:
    repo = RecordingRepo()
    items = [_item("setup.py", {"excerpt": "install_requires=['numpy']"})]

    async def embedder(text: str) -> list[float]:
        return [float(len(text))]

    await svc.persist_evidence(repo, project_id="prj_1", job_id=None, genome={}, items=items, embedder=embedder)

    assert repo.rows[0][6] == [float(len("install_requires=['numpy']"))]


def test_build_attempt_rows_mark_only_the_last_try_ok() -> None:
    emitted = [
        {"type": "build.attempt", "payload": {"attempt": 1}},
        {"type": "build.failed", "payload": {"attempt": 1, "reason": "module_not_found"}},
        {"type": "build.attempt", "payload": {"attempt": 2}},
        {"type": "test.attempt", "payload": {}},
    ]

    rows = svc.build_attempt_rows(emitted, attempts=2, build_ok=True)

    assert [(row["attempt"], row["ok"]) for row in rows] == [(1, False), (2, True)]
    assert rows[0]["error_fact"] == {"reason": "module_not_found"}
    assert rows[1]["error_fact"] == {}


def test_patch_rows_pair_proposals_with_the_applied_events() -> None:
    patches = [
        {"diff": "--- a\n+++ b\n", "touched_files": ["app.py"], "lines_added": 3, "lines_removed": 1},
        {"diff": "--- c\n+++ d\n", "touched_files": ["b.py", "c.py"], "lines_added": 2, "lines_removed": 2},
    ]
    emitted = [
        {"type": "repair.applied", "payload": {"applied": True, "attempt": 1}},
        {"type": "repair.applied", "payload": {"applied": False, "attempt": 2}},
    ]

    rows = svc.patch_rows(patches, emitted)

    assert [(row["entry"], row["accepted"], row["files_changed"], row["lines_changed"]) for row in rows] == [
        ("app.py", True, 1, 4),
        ("b.py", False, 2, 4),
    ]


def test_cursor_round_trip_and_validation() -> None:
    assert svc.decode_cursor(None) == 0
    encoded = svc.encode_cursor(40)
    assert svc.decode_cursor(encoded) == 40
    with pytest.raises(ValueError):
        svc.decode_cursor("####")


def test_public_projection_carries_the_digest_not_the_excerpt() -> None:
    record = type(
        "EvidenceRecord",
        (),
        {
            "id": "ev_1",
            "project_id": "prj_1",
            "source_kind": "manifest_file",
            "reference": "requirements.txt",
            "facts": {"dependencies": ["flask"]},
            "confidence": 0.5,
            "excerpt_hash": "deadbeef",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    )()

    view = svc.public_evidence(record)

    assert view["excerpt_hash"] == "deadbeef"
    assert "excerpt" not in view and "SECRET" not in repr(view)
    assert set(view) == {
        "id",
        "project_id",
        "source_kind",
        "reference",
        "facts",
        "confidence",
        "excerpt_hash",
        "created_at",
    }
