"""SQLAlchemy 2.x typed control-plane persistence models (T-BE-02).

Fifteen tables from `docs/tasks/05-后端API与数据层.md` T-BE-02 plus the two seams
the control plane already needs in `store.py` (`refresh_tokens`, `admin_audit`).
Rules kept from that ticket: string primary keys shaped `rev_<entity>_<hex>`,
every document column is JSONB, every timestamp is timestamptz in UTC, soft
delete exists only on `projects` and `capsules`, and every foreign key cascades.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIMENSIONS = 1536


class Base(DeclarativeBase):
    pass


class Timestamped(Base):
    __abstract__ = True
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Timestamped):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)

    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user", cascade="all, delete-orphan")
    projects: Mapped[list[Project]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ApiKey(Timestamped):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="api_keys")


class RefreshToken(Timestamped):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    family: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Project(Timestamped):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    repo_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="projects")
    repositories: Mapped[list[Repository]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[list[Job]] = relationship(back_populates="project", cascade="all, delete-orphan")
    evidence: Mapped[list[EvidenceItem]] = relationship(back_populates="project", cascade="all, delete-orphan")
    genomes: Mapped[list[Genome]] = relationship(back_populates="project", cascade="all, delete-orphan")
    fingerprints: Mapped[list[Fingerprint]] = relationship(back_populates="project", cascade="all, delete-orphan")
    capsules: Mapped[list[Capsule]] = relationship(back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_projects_user_repo", "user_id", "repo_key"),)


class Repository(Timestamped):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mirror_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    project: Mapped[Project] = relationship(back_populates="repositories")


class Job(Timestamped):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    admin_killed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    project: Mapped[Project] = relationship(back_populates="jobs")
    events: Mapped[list[JobEvent]] = relationship(back_populates="job", cascade="all, delete-orphan")
    build_attempts: Mapped[list[BuildAttempt]] = relationship(back_populates="job", cascade="all, delete-orphan")
    patches: Mapped[list[Patch]] = relationship(back_populates="job", cascade="all, delete-orphan")
    behavior_runs: Mapped[list[BehaviorRun]] = relationship(back_populates="job", cascade="all, delete-orphan")
    llm_calls: Mapped[list[LLMCall]] = relationship(back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_jobs_user_created", "user_id", "created_at"),)


class JobEvent(Timestamped):
    """One row per job-event.schema.json instance; payload is validated in the app layer."""

    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sequence: Mapped[int] = mapped_column(nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    job: Mapped[Job] = relationship(back_populates="events")

    __table_args__ = (Index("ix_job_events_job_sequence", "job_id", "sequence", unique=True),)


class EvidenceItem(Timestamped):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    reference: Mapped[str] = mapped_column(Text(), nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    excerpt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Nullable by contract: with no `REVIVE_LLM__EMBED_*` configured the column stays
    # NULL and retrieval degrades to confidence ordering instead of failing (T-BE-09).
    excerpt_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    project: Mapped[Project] = relationship(back_populates="evidence")

    __table_args__ = (
        Index("ix_evidence_project_confidence", "project_id", "confidence"),
        Index(
            "ix_evidence_items_excerpt_embedding",
            "excerpt_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"excerpt_embedding": "vector_cosine_ops"},
        ),
    )


class Genome(Timestamped):
    __tablename__ = "genomes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=True)
    python_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    os_image: Mapped[str | None] = mapped_column(String(256), nullable=True)
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    project: Mapped[Project] = relationship(back_populates="genomes")


class BuildAttempt(Timestamped):
    __tablename__ = "build_attempts"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="build", nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exit_code: Mapped[int | None] = mapped_column(nullable=True)
    output: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_fact: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    job: Mapped[Job] = relationship(back_populates="build_attempts")

    __table_args__ = (Index("ix_build_attempts_job_attempt", "job_id", "attempt", unique=True),)


class Patch(Timestamped):
    __tablename__ = "patches"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    entry: Mapped[str] = mapped_column(String(512), nullable=False)
    diff: Mapped[str] = mapped_column(Text(), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    files_changed: Mapped[int] = mapped_column(default=0, nullable=False)
    lines_changed: Mapped[int] = mapped_column(default=0, nullable=False)

    job: Mapped[Job] = relationship(back_populates="patches")


class BehaviorRun(Timestamped):
    __tablename__ = "behavior_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    plan_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cases: Mapped[int] = mapped_column(default=0, nullable=False)
    compatibility: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    job: Mapped[Job] = relationship(back_populates="behavior_runs")


class Fingerprint(Timestamped):
    __tablename__ = "fingerprints"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=True)
    plan_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    project: Mapped[Project] = relationship(back_populates="fingerprints")


class Capsule(Timestamped):
    __tablename__ = "capsules"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    object_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(default=0, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="capsules")


class LLMCall(Timestamped):
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    node: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ok", nullable=False)

    job: Mapped[Job | None] = relationship(back_populates="llm_calls")

    __table_args__ = (Index("ix_llm_calls_created_provider", "created_at", "provider"),)


class AdminAudit(Timestamped):
    __tablename__ = "admin_audit"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class RuntimeSetting(Timestamped):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class CaseMemory(Timestamped):
    __tablename__ = "case_memory"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), default="evidence", nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    __table_args__ = (
        Index(
            "ix_case_memory_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


__all__ = [
    "EMBEDDING_DIMENSIONS",
    "AdminAudit",
    "ApiKey",
    "Base",
    "BehaviorRun",
    "BuildAttempt",
    "Capsule",
    "CaseMemory",
    "EvidenceItem",
    "Fingerprint",
    "Genome",
    "Job",
    "JobEvent",
    "LLMCall",
    "Patch",
    "Project",
    "RefreshToken",
    "Repository",
    "RuntimeSetting",
    "Timestamped",
    "User",
]
