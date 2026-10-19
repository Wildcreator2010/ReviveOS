"""initial control-plane schema

Revision ID: 0001_init
Revises:
Create Date: 2026-10-10

Every table is written as explicit DDL (no ``create_all``) so the schema stays
reviewable and reversible; documents are JSONB, timestamps are timestamptz.
The pgvector column and the composite read-path indexes land in ``0002``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None

_NOW = sa.text("now()")


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False)


def _pk() -> sa.Column:
    return sa.Column("id", sa.String(length=128), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        _pk(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "api_keys",
        _pk(),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=512), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_api_keys_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
    )
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"])

    op.create_table(
        "refresh_tokens",
        _pk(),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("family", sa.String(length=128), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_refresh_tokens_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])
    op.create_index(op.f("ix_refresh_tokens_family"), "refresh_tokens", ["family"])

    op.create_table(
        "projects",
        _pk(),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("repo_url", sa.String(length=2048), nullable=False),
        sa.Column("repo_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_projects_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )
    op.create_index(op.f("ix_projects_user_id"), "projects", ["user_id"])

    op.create_table(
        "repositories",
        _pk(),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("commit_sha", sa.String(length=128), nullable=True),
        sa.Column("mirror_path", sa.String(length=2048), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_repositories_project_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_repositories"),
    )
    op.create_index(op.f("ix_repositories_project_id"), "repositories", ["project_id"])

    op.create_table(
        "jobs",
        _pk(),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("admin_killed", sa.Boolean(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_jobs_project_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_jobs_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    op.create_index(op.f("ix_jobs_project_id"), "jobs", ["project_id"])
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"])

    op.create_table(
        "job_events",
        _pk(),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_job_events_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_job_events"),
    )
    op.create_index(op.f("ix_job_events_job_id"), "job_events", ["job_id"])

    op.create_table(
        "evidence_items",
        _pk(),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("excerpt_hash", sa.String(length=64), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_evidence_items_project_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_evidence_items_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_items"),
    )
    op.create_index(op.f("ix_evidence_items_project_id"), "evidence_items", ["project_id"])
    op.create_index(op.f("ix_evidence_items_job_id"), "evidence_items", ["job_id"])

    op.create_table(
        "genomes",
        _pk(),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("python_version", sa.String(length=32), nullable=True),
        sa.Column("os_image", sa.String(length=256), nullable=True),
        sa.Column("overall_confidence", sa.Float(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_genomes_project_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_genomes_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_genomes"),
    )
    op.create_index(op.f("ix_genomes_project_id"), "genomes", ["project_id"])
    op.create_index(op.f("ix_genomes_job_id"), "genomes", ["job_id"])

    op.create_table(
        "build_attempts",
        _pk(),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error_fact", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_build_attempts_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_build_attempts"),
    )
    op.create_index(op.f("ix_build_attempts_job_id"), "build_attempts", ["job_id"])

    op.create_table(
        "patches",
        _pk(),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("entry", sa.String(length=512), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("files_changed", sa.Integer(), nullable=False),
        sa.Column("lines_changed", sa.Integer(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_patches_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_patches"),
    )
    op.create_index(op.f("ix_patches_job_id"), "patches", ["job_id"])

    op.create_table(
        "behavior_runs",
        _pk(),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("plan_ref", sa.String(length=512), nullable=True),
        sa.Column("cases", sa.Integer(), nullable=False),
        sa.Column("compatibility", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_behavior_runs_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_behavior_runs"),
    )
    op.create_index(op.f("ix_behavior_runs_job_id"), "behavior_runs", ["job_id"])

    op.create_table(
        "fingerprints",
        _pk(),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("plan_ref", sa.String(length=512), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_fingerprints_project_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_fingerprints_job_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_fingerprints"),
    )
    op.create_index(op.f("ix_fingerprints_project_id"), "fingerprints", ["project_id"])
    op.create_index(op.f("ix_fingerprints_job_id"), "fingerprints", ["job_id"])

    op.create_table(
        "capsules",
        _pk(),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=2048), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_capsules_project_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_capsules_job_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_capsules_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_capsules"),
    )
    op.create_index(op.f("ix_capsules_project_id"), "capsules", ["project_id"])
    op.create_index(op.f("ix_capsules_job_id"), "capsules", ["job_id"])
    op.create_index(op.f("ix_capsules_user_id"), "capsules", ["user_id"])

    op.create_table(
        "llm_calls",
        _pk(),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("node", sa.String(length=64), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_llm_calls_job_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_llm_calls_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_llm_calls"),
    )
    op.create_index(op.f("ix_llm_calls_job_id"), "llm_calls", ["job_id"])
    op.create_index(op.f("ix_llm_calls_user_id"), "llm_calls", ["user_id"])

    op.create_table(
        "admin_audit",
        _pk(),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_job_id", sa.String(length=128), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name="fk_admin_audit_actor_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["target_job_id"], ["jobs.id"], name="fk_admin_audit_target_job_id", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_audit"),
    )
    op.create_index(op.f("ix_admin_audit_actor_id"), "admin_audit", ["actor_id"])

    op.create_table(
        "case_memory",
        _pk(),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_case_memory_project_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_case_memory"),
    )


def downgrade() -> None:
    # DROP TABLE also removes the table's indexes and FK constraints, so the
    # reverse dependency order below is all that is required.
    for table in (
        "case_memory",
        "admin_audit",
        "llm_calls",
        "capsules",
        "fingerprints",
        "behavior_runs",
        "patches",
        "build_attempts",
        "genomes",
        "evidence_items",
        "job_events",
        "jobs",
        "repositories",
        "projects",
        "refresh_tokens",
        "api_keys",
        "users",
    ):
        op.drop_table(table)
