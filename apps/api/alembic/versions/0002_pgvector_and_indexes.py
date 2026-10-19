"""pgvector extension, embedding column and the read-path indexes

Revision ID: 0002_vectors
Revises: 0001_init
Create Date: 2026-10-10

``0001`` stays portable DDL; this revision is deliberately PostgreSQL-specific:
it enables the ``vector`` extension, gives ``case_memory`` its 1536-dimension
embedding with an HNSW index, and adds the composite indexes the list and
aggregation endpoints read through.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0002_vectors"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("case_memory", sa.Column("embedding", Vector(1536), nullable=True))
    op.create_index(
        "ix_case_memory_embedding",
        "case_memory",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_index("ix_projects_user_repo", "projects", ["user_id", "repo_key"])
    op.create_index("ix_jobs_user_created", "jobs", ["user_id", "created_at"])
    op.create_index("ix_job_events_job_sequence", "job_events", ["job_id", "sequence"], unique=True)
    op.create_index("ix_evidence_project_confidence", "evidence_items", ["project_id", "confidence"])
    op.create_index("ix_build_attempts_job_attempt", "build_attempts", ["job_id", "attempt"], unique=True)
    op.create_index("ix_llm_calls_created_provider", "llm_calls", ["created_at", "provider"])


def downgrade() -> None:
    for name, table in (
        ("ix_llm_calls_created_provider", "llm_calls"),
        ("ix_build_attempts_job_attempt", "build_attempts"),
        ("ix_evidence_project_confidence", "evidence_items"),
        ("ix_job_events_job_sequence", "job_events"),
        ("ix_jobs_user_created", "jobs"),
        ("ix_projects_user_repo", "projects"),
        ("ix_case_memory_embedding", "case_memory"),
    ):
        op.drop_index(name, table_name=table)
    op.drop_column("case_memory", "embedding")
    op.execute("DROP EXTENSION IF EXISTS vector")
