"""Async control-plane storage seam.

HTTP handlers depend on this small interface rather than dict-shaped stores. The
memory adapter keeps development and contract tests deterministic; the PostgreSQL
repository can be installed behind the same seam without leaking ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from .security import verify_password
from .store import (
    ApiKeyRecord,
    CapsuleRecord,
    EvidenceRecord,
    JobEventRecord,
    JobRecord,
    MemoryStore,
    ProjectRecord,
    RefreshRecord,
    UserRecord,
)


class ControlPlanePort(Protocol):
    durable: bool

    async def add_user(self, email: str, password_hash: str, role: str = "user") -> UserRecord: ...
    async def user_by_email(self, email: str) -> UserRecord | None: ...
    async def get_user(self, user_id: str) -> UserRecord | None: ...
    async def add_project(self, user_id: str, repo_url: str, repo_key: str = "") -> ProjectRecord: ...
    async def get_project(self, project_id: str) -> ProjectRecord | None: ...
    async def list_projects(self, user_id: str) -> list[ProjectRecord]: ...
    async def add_job(self, project_id: str, user_id: str) -> JobRecord: ...
    async def get_job(self, job_id: str) -> JobRecord | None: ...
    async def list_jobs(self, user_id: str, project_id: str | None = None) -> list[JobRecord]: ...
    async def update_job(self, job_id: str, **fields: Any) -> None: ...
    async def active_jobs(self, user_id: str) -> list[JobRecord]: ...
    async def jobs_today(self, user_id: str) -> int: ...
    async def update_project(self, project_id: str, **fields: Any) -> None: ...
    async def soft_delete_project(self, project_id: str) -> None: ...
    async def add_api_key(self, user_id: str, prefix: str, key_hash: str, label: str = "") -> ApiKeyRecord: ...
    async def list_api_keys(self, user_id: str) -> list[ApiKeyRecord]: ...
    async def get_api_key(self, key_id: str, user_id: str | None = None) -> ApiKeyRecord | None: ...
    async def find_api_key(self, token: str) -> ApiKeyRecord | None: ...
    async def revoke_api_key(self, key_id: str, user_id: str | None = None) -> bool: ...
    async def add_refresh_token(self, jti: str, family: str, user_id: str, expires_at: datetime) -> RefreshRecord: ...
    async def get_refresh_token(self, jti: str) -> RefreshRecord | None: ...
    async def mark_refresh_token_used(self, jti: str) -> bool: ...
    async def revoke_refresh_family(self, family: str) -> None: ...
    async def authenticate(self, email: str, password: str) -> UserRecord | None: ...
    async def list_evidence(
        self, project_id: str, source_kind: str | None = None, *, limit: int = 20, offset: int = 0
    ) -> list[EvidenceRecord]: ...
    async def add_evidence(
        self,
        project_id: str,
        source_kind: str,
        reference: str,
        facts: dict[str, Any],
        confidence: float = 0.0,
        excerpt: str | None = None,
    ) -> EvidenceRecord: ...
    async def latest_job(self, project_id: str) -> JobRecord | None: ...
    async def events_for_job(self, job_id: str, after: str | None = None) -> list[JobEventRecord]: ...
    async def is_maintenance(self) -> bool: ...
    async def set_maintenance(self, enabled: bool) -> None: ...
    async def list_admin_jobs(self, status: str | None = None) -> list[JobRecord]: ...
    async def llm_cost_by_provider(self, since: datetime) -> dict[str, float]: ...
    async def append_audit(
        self,
        actor_id: str,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
        target_job_id: str | None = None,
    ) -> None: ...
    async def commit_current(self) -> None: ...
    async def add_capsule(
        self,
        capsule_id: str,
        project_id: str,
        user_id: str,
        manifest: dict[str, Any],
        object_key: str,
        sha256: str,
        size_bytes: int,
        job_id: str | None = None,
    ) -> CapsuleRecord: ...
    async def get_capsule(self, capsule_id: str) -> CapsuleRecord | None: ...
    async def list_capsules(self, project_id: str) -> list[CapsuleRecord]: ...
    async def soft_delete_capsule(self, capsule_id: str) -> None: ...


class MemoryControlPlane:
    """Async adapter around MemoryStore for tests and local development only."""

    durable = False

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    async def add_user(self, email: str, password_hash: str, role: str = "user") -> UserRecord:
        return self.store.add_user(email, password_hash, role)

    async def user_by_email(self, email: str) -> UserRecord | None:
        return self.store.user_by_email(email)

    async def authenticate(self, email: str, password: str) -> UserRecord | None:
        user = self.store.user_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            return None
        return user

    async def list_evidence(
        self, project_id: str, source_kind: str | None = None, *, limit: int = 20, offset: int = 0
    ) -> list[EvidenceRecord]:
        items = [
            e
            for e in self.store.evidence.values()
            if e.project_id == project_id and (source_kind is None or e.source_kind == source_kind)
        ]
        items.sort(key=lambda item: (item.confidence, item.created_at), reverse=True)
        return items[offset : offset + limit]

    async def add_evidence(
        self,
        project_id: str,
        source_kind: str,
        reference: str,
        facts: dict[str, Any],
        confidence: float = 0.0,
        excerpt: str | None = None,
    ) -> EvidenceRecord:
        return self.store.add_evidence(project_id, source_kind, reference, facts, confidence, excerpt)

    async def latest_job(self, project_id: str) -> JobRecord | None:
        return next((job for job in reversed(list(self.store.jobs.values())) if job.project_id == project_id), None)

    async def events_for_job(self, job_id: str, after: str | None = None) -> list[JobEventRecord]:
        return self.store.events_for_job(job_id, after)

    async def is_maintenance(self) -> bool:
        return self.store.maintenance

    async def set_maintenance(self, enabled: bool) -> None:
        self.store.maintenance = enabled

    async def list_admin_jobs(self, status: str | None = None) -> list[JobRecord]:
        jobs = [job for job in self.store.jobs.values() if status is None or job.status == status]
        return sorted(jobs, key=lambda item: (item.created_at, item.id), reverse=True)

    async def llm_cost_by_provider(self, since: datetime) -> dict[str, float]:
        totals: dict[str, float] = {}
        for job in self.store.jobs.values():
            for provider, amount in job.metadata.get("llm_costs", {}).items():
                totals[provider] = totals.get(provider, 0.0) + float(amount)
        return totals

    async def append_audit(
        self,
        actor_id: str,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
        target_job_id: str | None = None,
    ) -> None:
        self.store.admin_audit.append(
            {"who": actor_id, "what": action, "job_id": target_job_id, "before": before, "after": after}
        )

    async def commit_current(self) -> None:
        return None

    async def get_user(self, user_id: str) -> UserRecord | None:
        return self.store.users.get(user_id)

    async def add_project(self, user_id: str, repo_url: str, repo_key: str = "") -> ProjectRecord:
        project = self.store.add_project(user_id, repo_url)
        if repo_key:
            project.metadata["repo_key"] = repo_key
        return project

    async def get_project(self, project_id: str) -> ProjectRecord | None:
        return self.store.projects.get(project_id)

    async def list_projects(self, user_id: str) -> list[ProjectRecord]:
        return sorted(
            [p for p in self.store.projects.values() if p.user_id == user_id and p.deleted_at is None],
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def add_job(self, project_id: str, user_id: str) -> JobRecord:
        project = self.store.projects[project_id]
        return self.store.add_job(project)

    async def get_job(self, job_id: str) -> JobRecord | None:
        return self.store.jobs.get(job_id)

    async def list_jobs(self, user_id: str, project_id: str | None = None) -> list[JobRecord]:
        return sorted(
            [
                j
                for j in self.store.jobs.values()
                if j.user_id == user_id and (project_id is None or j.project_id == project_id)
            ],
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def update_job(self, job_id: str, **fields: Any) -> None:
        job = self.store.jobs[job_id]
        for name, value in fields.items():
            if hasattr(job, name):
                setattr(job, name, value)

    async def active_jobs(self, user_id: str) -> list[JobRecord]:
        return self.store.active_jobs(user_id)

    async def jobs_today(self, user_id: str) -> int:
        return self.store.jobs_today(user_id)

    async def update_project(self, project_id: str, **fields: Any) -> None:
        project = self.store.projects[project_id]
        for name, value in fields.items():
            if name == "meta":
                project.metadata = dict(value)
            elif hasattr(project, name):
                setattr(project, name, value)

    async def soft_delete_project(self, project_id: str) -> None:
        project = self.store.projects[project_id]
        project.deleted_at = datetime.now().astimezone()
        project.status = "deleted"

    async def add_api_key(self, user_id: str, prefix: str, key_hash: str, label: str = "") -> ApiKeyRecord:
        from .store import ApiKeyRecord

        record = ApiKeyRecord(f"rev_api_key_{__import__('secrets').token_hex(10)}", user_id, prefix, key_hash, label)
        self.store.api_keys[record.id] = record
        return record

    async def list_api_keys(self, user_id: str) -> list[ApiKeyRecord]:
        return [key for key in self.store.api_keys.values() if key.user_id == user_id]

    async def get_api_key(self, key_id: str, user_id: str | None = None) -> ApiKeyRecord | None:
        key = self.store.api_keys.get(key_id)
        return key if key is not None and (user_id is None or key.user_id == user_id) else None

    async def find_api_key(self, token: str) -> ApiKeyRecord | None:
        from .security import verify_api_key

        for key in self.store.api_keys.values():
            if key.revoked_at is None and verify_api_key(token, key.key_hash):
                return key
        return None

    async def revoke_api_key(self, key_id: str, user_id: str | None = None) -> bool:
        key = await self.get_api_key(key_id, user_id)
        if key is None or key.revoked_at is not None:
            return False
        key.revoked_at = datetime.now().astimezone()
        return True

    async def add_refresh_token(self, jti: str, family: str, user_id: str, expires_at: datetime) -> RefreshRecord:
        record = RefreshRecord(jti, family, user_id, expires_at=expires_at)
        self.store.refresh_tokens[jti] = record
        return record

    async def get_refresh_token(self, jti: str) -> RefreshRecord | None:
        return self.store.refresh_tokens.get(jti)

    async def mark_refresh_token_used(self, jti: str) -> bool:
        record = self.store.refresh_tokens.get(jti)
        if record is None or record.used or record.revoked:
            return False
        record.used = True
        return True

    async def revoke_refresh_family(self, family: str) -> None:
        for record in self.store.refresh_tokens.values():
            if record.family == family:
                record.revoked = True

    async def add_capsule(
        self,
        capsule_id: str,
        project_id: str,
        user_id: str,
        manifest: dict[str, Any],
        object_key: str,
        sha256: str,
        size_bytes: int,
        job_id: str | None = None,
    ) -> CapsuleRecord:
        capsule = CapsuleRecord(
            id=capsule_id,
            project_id=project_id,
            user_id=user_id,
            object_key=object_key,
            manifest=manifest,
            content=b"",
            sha256=sha256,
        )
        self.store.capsules[capsule.id] = capsule
        return capsule

    async def get_capsule(self, capsule_id: str) -> CapsuleRecord | None:
        return self.store.capsules.get(capsule_id)

    async def list_capsules(self, project_id: str) -> list[CapsuleRecord]:
        return sorted(
            [c for c in self.store.capsules.values() if c.project_id == project_id and c.deleted_at is None],
            key=lambda item: (item.created_at, item.id),
            reverse=True,
        )

    async def soft_delete_capsule(self, capsule_id: str) -> None:
        capsule = self.store.capsules.get(capsule_id)
        if capsule is not None:
            capsule.deleted_at = datetime.now().astimezone()


def memory_control_plane(store: MemoryStore | None = None) -> MemoryControlPlane:
    return MemoryControlPlane(store)


__all__ = ["ControlPlanePort", "MemoryControlPlane", "memory_control_plane"]
