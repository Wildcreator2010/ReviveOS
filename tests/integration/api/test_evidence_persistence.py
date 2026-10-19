"""T-BE-09: archaeology artifacts and evidence retrieval against PostgreSQL.

Proves the four things the ticket cares about: the pipeline writes real
`genomes`/`evidence_items` rows, retrieval is confidence-ordered with a cursor that
continues, the excerpt text never lands in a row or a response (only its sha256),
and an unconfigured embedding endpoint degrades to a NULL vector instead of
failing the insert.
"""

from __future__ import annotations

from typing import Any

import pytest
from revive_api.services import evidence_service as svc
from revive_api.tasks.pipeline import execute_job
from revive_core.archaeology import EvidenceItem, EvidenceReference
from revive_core.schemas import SchemaError, validate
from sqlalchemy import text
from sqlalchemy.engine import URL
from test_pipeline import Sandbox, local_port, write_fixture_repo

pytestmark = pytest.mark.requires_docker

TEST_DB = "revive_evidence_test"


@pytest.fixture
async def sandbox(migrated_database: URL, tmp_path: Any):
    handle = await Sandbox.create(migrated_database)
    handle.source = write_fixture_repo(tmp_path)
    try:
        yield handle
    finally:
        await handle.close()


@pytest.fixture
def migrated_database(provision_database: Any) -> URL:
    return provision_database(TEST_DB)


def item(file: str, facts: dict[str, Any], confidence: float, excerpt: str | None = None) -> EvidenceItem:
    payload = dict(facts)
    if excerpt is not None:
        payload["excerpt"] = excerpt
    return EvidenceItem(source_kind="manifest_file", reference=EvidenceReference(file=file), facts=payload)


async def test_pipeline_persists_genome_and_evidence_rows(sandbox: Sandbox) -> None:
    job_id = await sandbox.seed("arch", sandbox.source)

    result = await execute_job(job_id, store=sandbox.store, events=sandbox.bus, execution_factory=local_port)
    assert result.status == "succeeded", result.failure_reason

    rows = await sandbox.session.execute(
        text("select python_version, overall_confidence from genomes where job_id = :j"), {"j": job_id}
    )
    genomes = rows.all()
    assert len(genomes) == 1

    evidence = (
        await sandbox.session.execute(
            text(
                "select reference, source_kind, confidence, "
                "excerpt_embedding is null as no_vector "
                "from evidence_items where job_id = :j order by confidence desc"
            ),
            {"j": job_id},
        )
    ).all()
    references = {row[0] for row in evidence}
    assert "requirements.txt" in references
    assert all(row[1] == "manifest_file" for row in evidence)
    # REVIVE_LLM__EMBED_* is unset in this environment: vectors stay NULL, inserts succeed.
    assert all(row[3] is True for row in evidence)

    counts = {
        table: (
            await sandbox.session.execute(text(f"select count(*) from {table} where job_id = :j"), {"j": job_id})
        ).scalar_one()
        for table in ("build_attempts", "behavior_runs")
    }
    assert counts["build_attempts"] >= 1
    assert counts["behavior_runs"] == 1


async def test_evidence_page_is_confidence_ordered_and_the_cursor_continues(sandbox: Sandbox) -> None:
    user = await sandbox.repository.add_user("page@e.example", "hash")
    project = await sandbox.repository.add_project(user.id, "https://github.com/acme/page", "acme/page")

    for name, confidence in (("a.txt", 0.9), ("b.txt", 0.2), ("c.txt", 0.7), ("d.txt", 0.5)):
        await sandbox.repository.add_evidence(
            project.id, "manifest_file", name, {"rank": name}, confidence, None, None, None
        )
    await sandbox.repository.commit()

    first = await svc.evidence_page(sandbox.repository, project.id, limit=2)
    second = await svc.evidence_page(sandbox.repository, project.id, limit=2, cursor=first["next_cursor"])

    assert [row["reference"] for row in first["items"]] == ["a.txt", "c.txt"]
    assert [row["reference"] for row in second["items"]] == ["d.txt", "b.txt"]
    assert first["next_cursor"] and second["next_cursor"] is None
    assert all("excerpt" not in row for page in (first, second) for row in page["items"])


async def test_source_kind_filter_and_limit_validation(sandbox: Sandbox) -> None:
    user = await sandbox.repository.add_user("filter@e.example", "hash")
    project = await sandbox.repository.add_project(user.id, "https://github.com/acme/filter", "acme/filter")
    await sandbox.repository.add_evidence(project.id, "manifest_file", "setup.py", {}, 0.8, None, None, None)
    await sandbox.repository.add_evidence(
        project.id, "ci_config", ".github/workflows/ci.yml", {}, 0.6, None, None, None
    )
    await sandbox.repository.commit()

    only_ci = await svc.evidence_page(sandbox.repository, project.id, source_kind="ci_config")

    assert [row["source_kind"] for row in only_ci["items"]] == ["ci_config"]
    with pytest.raises(ValueError):
        await svc.evidence_page(sandbox.repository, project.id, limit=0)


async def test_excerpt_text_is_never_stored_or_returned(sandbox: Sandbox) -> None:
    user = await sandbox.repository.add_user("leak@e.example", "hash")
    project = await sandbox.repository.add_project(user.id, "https://github.com/acme/leak", "acme/leak")
    secret = "aws-access-token=ASIALEAKME"
    items = [item("private.txt", {"dependencies": ["flask==1.1.4"]}, 0.5, excerpt=secret)]

    written = await svc.persist_evidence(
        sandbox.repository, project_id=project.id, job_id=None, genome={}, items=items, embedder=None
    )
    await sandbox.repository.commit()

    assert written == 1
    page = await svc.evidence_page(sandbox.repository, project.id)
    assert secret not in repr(page)
    digest = page["items"][0]["excerpt_hash"]
    assert digest and len(digest) == 64
    stored = (
        await sandbox.session.execute(
            text("select facts::text, excerpt_hash, excerpt_embedding from evidence_items where project_id = :p"),
            {"p": project.id},
        )
    ).one()
    assert secret not in stored[0]
    assert "excerpt" not in stored[0]
    assert stored[1] == digest
    assert stored[2] is None


async def test_vector_is_stored_when_an_embedder_is_present(sandbox: Sandbox) -> None:
    user = await sandbox.repository.add_user("vector@e.example", "hash")
    project = await sandbox.repository.add_project(user.id, "https://github.com/acme/vector", "acme/vector")
    vector = [0.5] * 1536
    items = [item("pinned.txt", {"dependencies": ["numpy==1.16"]}, 0.4, excerpt="numpy==1.16")]

    async def embedder(text: str) -> list[float]:
        return vector

    await svc.persist_evidence(
        sandbox.repository, project_id=project.id, job_id=None, genome={}, items=items, embedder=embedder
    )
    await sandbox.repository.commit()

    stored = (
        await sandbox.session.execute(
            text("select excerpt_hash, excerpt_embedding::text from evidence_items where project_id = :p"),
            {"p": project.id},
        )
    ).one()
    assert stored[0]  # digest recorded
    assert stored[1].startswith("[0.5,0.5")


async def test_genome_rows_survive_the_contract(sandbox: Sandbox) -> None:
    user = await sandbox.repository.add_user("contract@e.example", "hash")
    project = await sandbox.repository.add_project(user.id, "https://github.com/acme/contract", "acme/contract")
    genome = {
        "python": {
            "version": "3.11",
            "confidence": 0.9,
            "evidence": [{"source_kind": "manifest_file", "reference": "pyproject.toml"}],
        },
        "os": {"image": "ubuntu:22.04", "confidence": 0.5, "evidence": []},
        "dependencies": [],
        "cuda": {"confidence": 0.0, "evidence": []},
        "system_libs": [],
        "overall_confidence": 0.7,
    }
    validate(genome, "genome")

    genome_id = await sandbox.repository.add_genome(project.id, genome)
    await sandbox.repository.add_evidence(
        project.id,
        "manifest_file",
        "pyproject.toml",
        {"requires-python": ">=3.11"},
        svc.confidence_by_reference(genome)["pyproject.toml"],
        None,
        None,
        None,
    )
    await sandbox.repository.commit()

    row = (
        await sandbox.session.execute(
            text("select python_version, os_image, overall_confidence from genomes where id = :i"), {"i": genome_id}
        )
    ).one()
    assert row == ("3.11", "ubuntu:22.04", pytest.approx(0.7))
    page = await svc.evidence_page(sandbox.repository, project.id)
    assert page["items"][0]["confidence"] == pytest.approx(0.9)

    with pytest.raises(SchemaError):
        validate({"python": {"confidence": 2.0, "evidence": []}}, "genome")
