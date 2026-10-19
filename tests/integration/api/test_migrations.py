"""T-BE-02: real PostgreSQL migrations + repository, on a throwaway schema.

Covers the ticket's acceptance verbatim: `upgrade head` creates every table, the
pgvector column and HNSW index exist, `downgrade base` empties the schema, the
hand-written migrations leave no drift against the ORM models, and the repository
reads and writes through them.  Runs with `REVIVE_DOCKER_AVAILABLE=1` + DATABASE_URL.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from db_provision import alembic_config, open_engine, sync_url
from revive_api.db.models import Base
from revive_api.db.repository import ControlPlaneRepository
from revive_core import schemas
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.requires_docker

TEST_DB = "revive_migrations_test"

EXPECTED_TABLES = {
    "users",
    "api_keys",
    "refresh_tokens",
    "projects",
    "repositories",
    "jobs",
    "job_events",
    "evidence_items",
    "genomes",
    "build_attempts",
    "patches",
    "behavior_runs",
    "fingerprints",
    "capsules",
    "llm_calls",
    "admin_audit",
    "case_memory",
    "runtime_settings",
}


@pytest.fixture
def migrated(provision_database: Any) -> URL:
    return provision_database(TEST_DB)


def table_names(url: URL) -> set[str]:
    engine = open_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_every_table_and_downgrade_empties_them(migrated: URL) -> None:
    sync = sync_url(TEST_DB)
    engine = open_engine(sync)
    try:
        db = inspect(engine)
        assert EXPECTED_TABLES <= set(db.get_table_names())
        assert all(column["nullable"] for column in db.get_columns("case_memory") if column["name"] == "embedding")
        with engine.connect() as connection:
            udt = connection.execute(
                text(
                    "select udt_name from information_schema.columns "
                    "where table_name = 'case_memory' and column_name = 'embedding'"
                )
            ).scalar_one()
            hnsw = connection.execute(
                text("select indexdef from pg_indexes where indexname = 'ix_case_memory_embedding'")
            ).scalar_one()
            rules = [
                (table, foreign_key["referred_table"], foreign_key["options"].get("ondelete"))
                for table in ("job_events", "jobs", "capsules", "evidence_items")
                for foreign_key in db.get_foreign_keys(table)
            ]
        assert udt == "vector"
        assert "USING hnsw" in hnsw and "vector_cosine_ops" in hnsw
        assert ("job_events", "jobs", "CASCADE") in rules
        assert ("jobs", "projects", "CASCADE") in rules
        assert {option for _, _, option in rules} == {"CASCADE"}
    finally:
        engine.dispose()

    command.downgrade(alembic_config(), "base")
    assert table_names(sync) == {"alembic_version"}

    command.upgrade(alembic_config(), "head")
    assert EXPECTED_TABLES <= table_names(sync)


def test_migrations_leave_no_model_drift(migrated: URL) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = open_engine(sync_url(TEST_DB))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


async def test_repository_writes_and_reads_through_the_schema(migrated: URL) -> None:
    engine = create_async_engine(migrated.render_as_string(hide_password=False))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            store = ControlPlaneRepository(session)

            user = await store.add_user("Repo.Test@Example.com", "hash")
            assert (await store.user_by_email("repo.test@example.com")).id == user.id
            with pytest.raises(ValueError):
                await store.add_user("repo.test@example.com", "other")

            project = await store.add_project(user.id, "https://github.com/acme/repo", "acme/repo")
            await store.update_project(project.id, meta={"repo_size_mb": 12})
            assert (await store.get_project(project.id)).metadata == {"repo_size_mb": 12}

            job = await store.add_job(project.id, user.id)
            await store.update_job(job.id, status="running")
            await store.set_job_metadata(job.id, genome={"python": {"version": "3.11"}})
            reloaded = await store.get_job(job.id)
            assert reloaded.status == "running"
            assert reloaded.metadata["genome"]["python"]["version"] == "3.11"
            assert [item.id for item in await store.active_jobs(user.id)] == [job.id]
            assert await store.jobs_today(user.id) == 1

            for attempt in range(1, 4):
                await store.add_event(job.id, "build.attempt", {"attempt": attempt, "ok": attempt == 3})
            await store.commit()
            events = await store.events_for_job(job.id)
            assert [event.sequence for event in events] == [1, 2, 3]
            assert events[-1].payload == {"attempt": 3, "ok": True}
            assert {event.project_id for event in events} == {project.id}
            assert [event.sequence for event in await store.events_for_job(job.id, 2)] == [3]
            for event in events:
                schemas.validate(event.as_dict(), "job-event")

            await store.add_evidence(project.id, "manifest_file", "pyproject.toml", {"a": 1}, 0.9, "excerpt")
            await store.add_evidence(project.id, "ci_config", ".github/workflows/ci.yml", {}, 0.4)
            await store.commit()
            assert [item.source_kind for item in await store.list_evidence(project.id)] == [
                "manifest_file",
                "ci_config",
            ]
            filtered = await store.list_evidence(project.id, "ci_config")
            assert [item.source_kind for item in filtered] == ["ci_config"]
            assert filtered[0].excerpt_hash is None

            capsule = await store.add_capsule(
                project.id,
                user.id,
                {"format": "revive/v1"},
                f"capsules/{user.id}/capsule_test.revive",
                hashlib.sha256(b"payload").hexdigest(),
                len(b"payload"),
            )
            assert capsule.object_key == f"capsules/{user.id}/capsule_test.revive"
            await store.soft_delete_capsule(capsule.id)
            await store.commit()
            assert await store.list_capsules(project.id) == []
            assert [item.id for item in await store.list_capsules(project.id, include_deleted=True)] == [capsule.id]

            key = await store.add_api_key(user.id, "rev_abc", "digest", label="cli")
            await store.revoke_api_key(key.id)
            await store.commit()
            stored_keys = await store.api_keys()
            assert [item.id for item in stored_keys] == [key.id]
            assert stored_keys[0].revoked_at is not None

            await store.add_refresh_token("jti-1", "family-1", user.id, datetime.now(UTC))
            record = await store.get_refresh_token("jti-1")
            record.used = True
            await store.save_refresh_token(record)
            await store.revoke_refresh_family("family-1")
            await store.commit()
            stored = await store.get_refresh_token("jti-1")
            assert stored.used and stored.revoked

            await store.record_llm_call("openai", "gpt-4o", {"input_tokens": 10}, 0.25, job_id=job.id)
            await store.record_llm_call("anthropic", "claude", {"input_tokens": 4}, 0.10, job_id=job.id)
            await store.append_audit(user.id, "kill_job", {"status": "running"}, {"status": "cancelled"}, job.id)
            await store.commit()
            midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            costs = await store.llm_cost_by_provider(midnight)
            assert costs == {"openai": pytest.approx(0.25), "anthropic": pytest.approx(0.10)}
            audit = (
                (
                    await session.execute(
                        text("select action from admin_audit where actor_id = :actor"), {"actor": user.id}
                    )
                )
                .scalars()
                .all()
            )
            assert audit == ["kill_job"]

            # ON DELETE CASCADE: projects -> jobs -> job_events.
            await session.execute(text("delete from projects where id = :pid"), {"pid": project.id})
            await store.commit()
            assert await store.get_job(job.id) is None
            assert await store.events_for_job(job.id) == []
    finally:
        await engine.dispose()
