"""Deterministic in-memory control-plane repository used by tests and dev fallback."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any


def _now() -> datetime:
    return datetime.now(UTC)


def _id(kind: str) -> str:
    return f"rev_{kind}_{secrets.token_hex(10)}"


@dataclass
class UserRecord:
    id: str
    email: str
    password_hash: str
    role: str = "user"
    created_at: datetime = field(default_factory=_now)


@dataclass
class ApiKeyRecord:
    id: str
    user_id: str
    prefix: str
    key_hash: str
    label: str | None = None
    created_at: datetime = field(default_factory=_now)
    revoked_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass
class ProjectRecord:
    id: str
    user_id: str
    repo_url: str
    status: str = "created"
    created_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobRecord:
    id: str
    project_id: str
    user_id: str
    status: str = "queued"
    created_at: datetime = field(default_factory=_now)
    cancel_requested: bool = False
    admin_killed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceRecord:
    id: str
    project_id: str
    source_kind: str
    reference: str
    facts: dict[str, Any]
    confidence: float = 0.0
    excerpt_hash: str | None = None
    created_at: datetime = field(default_factory=_now)


@dataclass
class CapsuleRecord:
    id: str
    project_id: str
    user_id: str
    object_key: str
    manifest: dict[str, Any]
    content: bytes
    sha256: str
    created_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class JobEventRecord:
    id: str
    sequence: int
    job_id: str
    project_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        """Render the envelope exactly as schemas/job-event.schema.json fixes it."""

        return {
            "id": self.id,
            "job_id": self.job_id,
            "project_id": self.project_id,
            "ts": self.created_at.isoformat(),
            "type": self.event_type,
            "payload": self.payload,
        }


@dataclass
class RefreshRecord:
    jti: str
    family: str
    user_id: str
    used: bool = False
    revoked: bool = False
    expires_at: datetime = field(default_factory=lambda: _now() + timedelta(days=7))


class EventBus:
    """Persistence plus a lightweight pub/sub seam for SSE and workers."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self._queues: dict[str, list[asyncio.Queue[JobEventRecord]]] = {}

    def publish(self, job_id: str, event_type: str, payload: dict[str, Any] | None = None) -> JobEventRecord:
        event = self.store.add_event(job_id, event_type, payload or {})
        for queue in self._queues.get(job_id, []):
            queue.put_nowait(event)
        return event

    def subscribe(self, job_id: str) -> asyncio.Queue[JobEventRecord]:
        queue: asyncio.Queue[JobEventRecord] = asyncio.Queue()
        self._queues.setdefault(job_id, []).append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[JobEventRecord]) -> None:
        queues = self._queues.get(job_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._queues.pop(job_id, None)


MAX_EVENT_REPLAY = 5000


class MemoryStore:
    """A process-local substitute for PostgreSQL, Redis and object storage."""

    requires_docker = False
    durable = False

    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.users_by_email: dict[str, str] = {}
        self.api_keys: dict[str, ApiKeyRecord] = {}
        self.projects: dict[str, ProjectRecord] = {}
        self.jobs: dict[str, JobRecord] = {}
        self.evidence: dict[str, EvidenceRecord] = {}
        self.capsules: dict[str, CapsuleRecord] = {}
        self.events: dict[str, JobEventRecord] = {}
        self.events_by_job: dict[str, list[str]] = {}
        self.refresh_tokens: dict[str, RefreshRecord] = {}
        self.login_failures: dict[str, tuple[int, datetime]] = {}
        self.admin_audit: list[dict[str, Any]] = []
        self.runtime_settings: dict[str, dict[str, Any]] = {}
        self.maintenance = False
        self._event_sequence = 0
        self.event_bus = EventBus(self)

    def add_user(self, email: str, password_hash: str, role: str = "user") -> UserRecord:
        normalized = email.strip().lower()
        if normalized in self.users_by_email:
            raise ValueError("email already registered")
        user = UserRecord(_id("user"), normalized, password_hash, role)
        self.users[user.id] = user
        self.users_by_email[normalized] = user.id
        return user

    def user_by_email(self, email: str) -> UserRecord | None:
        user_id = self.users_by_email.get(email.strip().lower())
        return self.users.get(user_id) if user_id else None

    def add_project(self, user_id: str, repo_url: str) -> ProjectRecord:
        project = ProjectRecord(_id("project"), user_id, repo_url)
        self.projects[project.id] = project
        return project

    def add_job(self, project: ProjectRecord) -> JobRecord:
        job = JobRecord(_id("job"), project.id, project.user_id)
        self.jobs[job.id] = job
        project.status = "queued"
        return job

    def add_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> JobEventRecord:
        self._event_sequence += 1
        sequence = self._event_sequence
        job = self.jobs.get(job_id)
        event = JobEventRecord(
            id=f"evt_{sequence:012d}",
            sequence=sequence,
            job_id=job_id,
            project_id=job.project_id if job else "",
            event_type=event_type,
            payload=payload,
        )
        self.events[event.id] = event
        self.events_by_job.setdefault(job_id, []).append(event.id)
        return event

    def events_for_job(self, job_id: str, after: str | int | None = None) -> list[JobEventRecord]:
        start = 0
        if isinstance(after, int):
            start = max(after, 0)
        elif after:
            existing = self.events.get(after)
            if existing:
                start = existing.sequence
            elif str(after).isdigit():
                start = int(after)
        return [
            self.events[event_id]
            for event_id in self.events_by_job.get(job_id, [])
            if self.events[event_id].sequence > start
        ][-MAX_EVENT_REPLAY:]

    def active_jobs(self, user_id: str) -> list[JobRecord]:
        return [
            job
            for job in self.jobs.values()
            if job.user_id == user_id and job.status in {"queued", "running", "cancel_requested"}
        ]

    def jobs_today(self, user_id: str) -> int:
        today = _now().date()
        return sum(1 for job in self.jobs.values() if job.user_id == user_id and job.created_at.date() == today)

    def add_evidence(
        self,
        project_id: str,
        source_kind: str,
        reference: str,
        facts: dict[str, Any],
        confidence: float = 0.0,
        excerpt: str | None = None,
    ) -> EvidenceRecord:
        digest = hashlib.sha256(excerpt.encode()).hexdigest() if excerpt else None
        item = EvidenceRecord(_id("evidence"), project_id, source_kind, reference, facts, confidence, digest)
        self.evidence[item.id] = item
        return item

    def add_capsule(
        self,
        project: ProjectRecord,
        manifest: dict[str, Any],
        content: bytes,
    ) -> CapsuleRecord:
        digest = hashlib.sha256(content).hexdigest()
        capsule_id = _id("capsule")
        capsule = CapsuleRecord(
            capsule_id,
            project.id,
            project.user_id,
            f"capsules/{project.user_id}/{capsule_id}.revive",
            manifest,
            content,
            digest,
        )
        self.capsules[capsule.id] = capsule
        return capsule

    @staticmethod
    def decode_content(value: str) -> bytes:
        try:
            return base64.b64decode(value, validate=True)
        except Exception:
            return value.encode()


__all__ = [
    "ApiKeyRecord",
    "CapsuleRecord",
    "EvidenceRecord",
    "EventBus",
    "JobEventRecord",
    "JobRecord",
    "MemoryStore",
    "ProjectRecord",
    "RefreshRecord",
    "UserRecord",
]
