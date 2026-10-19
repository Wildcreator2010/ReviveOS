"""evidence excerpt embeddings

Revision ID: 0003_evidence_embeddings
Revises: 0002_vectors
Create Date: 2026-10-10

T-BE-09 stores only the excerpt digest; the vector column is nullable so a
deployment without `REVIVE_LLM__EMBED_*` keeps working (confidence ordering only)
instead of failing every insert.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0003_evidence_embeddings"
down_revision = "0002_vectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence_items", sa.Column("excerpt_embedding", Vector(1536), nullable=True))
    op.create_index(
        "ix_evidence_items_excerpt_embedding",
        "evidence_items",
        ["excerpt_embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"excerpt_embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_items_excerpt_embedding", table_name="evidence_items")
    op.drop_column("evidence_items", "excerpt_embedding")
