"""PostgreSQL control-plane repository (T-BE-02 write/read seam).

Same record dataclasses as `store.MemoryStore`, so callers keep one shape, but
every write is explicit: this repository never hands out an object and expects a
later in-place mutation to reach the database. `MemoryStore` supports
`store.jobs[id].status = "failed"` because it owns the objects; durable storage
needs a transaction boundary, which the route layer does not have yet. Wiring
this into `create_app(store=...)` is therefore part of the routers/services split
(`docs/tasks/05` T-BE-03/T-BE-05), not of this ticket.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..store import (
    ApiKeyRecord,
    CapsuleRecord,
    EvidenceRecord,
    JobEventRecord,
    JobRecord,
    ProjectRecord,
    RefreshRecord,
    UserRecord,
)
from .models import (
    AdminAudit,
    ApiKey,
    BehaviorRun,
    BuildAttempt,
    Capsule,
    EvidenceItem,
    Fingerprint,
    Genome,
    Job,
    JobEvent,
    LLMCall,
    Patch,
    Project,
    RefreshToken,
    RuntimeSetting,
    User,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _id(kind: str) -> str:
    return f"rev_{kind}_{secrets.token_hex(10)}"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _cursor_sequence(cursor: str | int | None) -> int:
    """Accept an event id (`evt_<job>_000...042`), a bare sequence, or an int."""

    if cursor is None:
        return 0
    if isinstance(cursor, int):
        return max(cursor, 0)
    text = str(cursor).strip()
    if not text:
        return 0
    tail = text.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


class ControlPlaneRepository:
    """Async repository over the T-BE-02 tables, on a caller-owned session."""

    durable = True
    requires_docker = True

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def flush(self) -> None:
        await self.session.flush()

    # -- users / keys ----------------------------------------------------
    async def add_user(self, email: str, password_hash: str, role: str = "user") -> UserRecord:
        normalized = email.strip().lower()
        if await self.user_by_email(normalized) is not None:
            raise ValueError("email already registered")
        row = User(id=_id("user"), email=normalized, password_hash=password_hash, role=role)
        self.session.add(row)
        try:
            await self.flush()
        except IntegrityError as exc:
            # A concurrent registration can pass the pre-check and hit the unique index.
            raise ValueError("email already registered") from exc
        return self._to_user_record(row)

    async def get_user(self, user_id: str) -> UserRecord | None:
        row = await self.session.get(User, user_id)
        return self._to_user_record(row) if row else None

    async def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return await self.get_user(user_id)

    async def user_by_email(self, email: str) -> UserRecord | None:
        row = (await self.session.scalars(select(User).where(User.email == email.strip().lower()))).one_or_none()
        return self._to_user_record(row) if row else None

    async def authenticate(self, email: str, password: str) -> UserRecord | None:
        from ..security import verify_password

        user = await self.user_by_email(email)
        if user is None:
            return None
        # Argon2 is CPU-bound; keep the event loop responsive under login load.
        if not await run_in_threadpool(verify_password, password, user.password_hash):
            return None
        return user

    async def add_api_key(self, user_id: str, prefix: str, key_hash: str, label: str = "") -> ApiKeyRecord:
        row = ApiKey(id=_id("api_key"), user_id=user_id, prefix=prefix, key_hash=key_hash, label=label)
        self.session.add(row)
        await self.flush()
        return self._to_api_key_record(row)

    async def api_keys(self) -> list[ApiKeyRecord]:
        rows = (await self.session.scalars(select(ApiKey))).all()
        return [self._to_api_key_record(row) for row in rows]

    async def list_api_keys(self, user_id: str) -> list[ApiKeyRecord]:
        rows = (
            await self.session.scalars(
                select(ApiKey)
                .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
                .order_by(ApiKey.created_at.desc())
            )
        ).all()
        return [self._to_api_key_record(row) for row in rows]

    async def get_api_key(self, key_id: str, user_id: str | None = None) -> ApiKeyRecord | None:
        statement = select(ApiKey).where(ApiKey.id == key_id)
        if user_id is not None:
            statement = statement.where(ApiKey.user_id == user_id)
        row = (await self.session.scalars(statement)).one_or_none()
        return self._to_api_key_record(row) if row is not None else None

    async def find_api_key(self, token: str) -> ApiKeyRecord | None:
        # The stored prefix narrows the candidate set; the hash still decides.
        # Verifying every key with Argon2 would make each request O(all keys).
        from ..security import verify_api_key

        rows = (
            await self.session.scalars(select(ApiKey).where(ApiKey.revoked_at.is_(None), ApiKey.prefix == token[:8]))
        ).all()
        for row in rows:
            if await run_in_threadpool(verify_api_key, token, row.key_hash):
                return self._to_api_key_record(row)
        return None

    async def revoke_api_key(self, key_id: str, user_id: str | None = None) -> bool:
        statement = update(ApiKey).where(ApiKey.id == key_id, ApiKey.revoked_at.is_(None))
        if user_id is not None:
            statement = statement.where(ApiKey.user_id == user_id)
        result = await self.session.execute(statement.values(revoked_at=_now()))
        return bool(cast("CursorResult[Any]", result).rowcount)

    async def add_refresh_token(self, jti: str, family: str, user_id: str, expires_at: datetime) -> RefreshRecord:
        self.session.add(RefreshToken(id=jti, family=family, user_id=user_id, expires_at=expires_at))
        await self.flush()
        return RefreshRecord(jti, family, user_id, expires_at=expires_at)

    async def get_refresh_token(self, jti: str) -> RefreshRecord | None:
        row = await self.session.get(RefreshToken, jti)
        if row is None:
            return None
        return RefreshRecord(
            row.id, row.family, row.user_id, used=row.used, revoked=row.revoked, expires_at=_utc(row.expires_at)
        )

    async def save_refresh_token(self, record: RefreshRecord) -> None:
        await self.session.execute(
            update(RefreshToken).where(RefreshToken.id == record.jti).values(used=record.used, revoked=record.revoked)
        )

    async def mark_refresh_token_used(self, jti: str) -> bool:
        result = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == jti, RefreshToken.used.is_(False), RefreshToken.revoked.is_(False))
            .values(used=True)
        )
        return bool(cast("CursorResult[Any]", result).rowcount)

    async def revoke_refresh_family(self, family: str) -> None:
        await self.session.execute(update(RefreshToken).where(RefreshToken.family == family).values(revoked=True))

    # -- projects / jobs -------------------------------------------------
    async def add_project(self, user_id: str, repo_url: str, repo_key: str = "") -> ProjectRecord:
        row = Project(id=_id("project"), user_id=user_id, repo_url=repo_url, repo_key=repo_key or repo_url)
        self.session.add(row)
        await self.flush()
        return self._to_project_record(row)

    async def get_project(self, project_id: str) -> ProjectRecord | None:
        row = await self.session.get(Project, project_id)
        return self._to_project_record(row) if row else None

    async def list_projects(self, user_id: str, *, include_deleted: bool = False) -> list[ProjectRecord]:
        statement = select(Project).where(Project.user_id == user_id)
        if not include_deleted:
            statement = statement.where(Project.deleted_at.is_(None))
        rows = (await self.session.scalars(statement.order_by(Project.created_at.desc()))).all()
        return [self._to_project_record(row) for row in rows]

    async def update_project(self, project_id: str, **fields: Any) -> None:
        if fields:
            await self.session.execute(update(Project).where(Project.id == project_id).values(**fields))

    async def soft_delete_project(self, project_id: str) -> None:
        await self.update_project(project_id, deleted_at=_now(), status="deleted")

    async def add_job(self, project_id: str, user_id: str, metadata: dict[str, Any] | None = None) -> JobRecord:
        row = Job(id=_id("job"), project_id=project_id, user_id=user_id, meta=dict(metadata or {}))
        self.session.add(row)
        await self.flush()
        await self.update_project(project_id, status="queued")
        return self._to_job_record(row)

    async def get_job(self, job_id: str) -> JobRecord | None:
        row = await self.session.get(Job, job_id)
        return self._to_job_record(row) if row else None

    async def list_jobs(self, user_id: str, project_id: str | None = None) -> list[JobRecord]:
        statement = select(Job).where(Job.user_id == user_id)
        if project_id is not None:
            statement = statement.where(Job.project_id == project_id)
        rows = (await self.session.scalars(statement.order_by(Job.created_at.desc()))).all()
        return [self._to_job_record(row) for row in rows]

    async def update_job(self, job_id: str, **fields: Any) -> None:
        if fields:
            await self.session.execute(update(Job).where(Job.id == job_id).values(**fields))

    async def active_jobs(self, user_id: str) -> list[JobRecord]:
        rows = (
            await self.session.scalars(
                select(Job).where(Job.user_id == user_id, Job.status.in_(("queued", "running", "cancel_requested")))
            )
        ).all()
        return [self._to_job_record(row) for row in rows]

    async def jobs_today(self, user_id: str) -> int:
        start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        count = await self.session.scalar(
            select(func.count()).select_from(Job).where(Job.user_id == user_id, Job.created_at >= start)
        )
        return int(count or 0)

    async def set_job_metadata(self, job_id: str, **values: Any) -> None:
        job = await self.session.get(Job, job_id)
        if job is None:
            return
        merged = {**(job.meta or {}), **values}
        await self.session.execute(update(Job).where(Job.id == job_id).values(meta=merged))

    # -- events ----------------------------------------------------------
    async def add_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> JobEventRecord:
        job = await self.session.get(Job, job_id)
        if job is None:
            raise KeyError(f"unknown job {job_id!r}")
        last = await self.session.scalar(
            select(func.coalesce(func.max(JobEvent.sequence), 0)).where(JobEvent.job_id == job_id)
        )
        sequence = int(last or 0) + 1
        row = JobEvent(
            # Job-scoped sequence, but the primary key is global: keep the job id in
            # the id or the first event of every job would collide on evt_...0001.
            id=f"evt_{job_id}_{sequence:012d}",
            sequence=sequence,
            job_id=job_id,
            project_id=job.project_id,
            event_type=event_type,
            payload=payload,
        )
        self.session.add(row)
        await self.flush()
        return JobEventRecord(
            id=row.id,
            sequence=sequence,
            job_id=job_id,
            project_id=job.project_id,
            event_type=event_type,
            payload=payload,
            created_at=_utc(row.created_at),
        )

    async def events_for_job(self, job_id: str, after: str | int | None = None) -> list[JobEventRecord]:
        after_sequence = _cursor_sequence(after)
        rows = (
            await self.session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id, JobEvent.sequence > after_sequence)
                .order_by(JobEvent.sequence)
            )
        ).all()
        return [
            JobEventRecord(
                id=row.id,
                sequence=row.sequence,
                job_id=row.job_id,
                project_id=row.project_id,
                event_type=row.event_type,
                payload=row.payload,
                created_at=_utc(row.created_at),
            )
            for row in rows
        ]

    # -- evidence --------------------------------------------------------
    async def latest_job(self, project_id: str) -> JobRecord | None:
        row = (
            await self.session.scalars(
                select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc(), Job.id.desc()).limit(1)
            )
        ).first()
        return self._to_job_record(row) if row is not None else None

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
    ) -> EvidenceRecord:
        digest = hashlib.sha256(excerpt.encode()).hexdigest() if excerpt else None
        row = EvidenceItem(
            id=_id("evidence"),
            project_id=project_id,
            job_id=job_id,
            source_kind=source_kind,
            reference=reference,
            facts=facts,
            confidence=confidence,
            excerpt_hash=digest,
            excerpt_embedding=excerpt_embedding,
        )
        self.session.add(row)
        await self.flush()
        return EvidenceRecord(
            id=row.id,
            project_id=project_id,
            source_kind=source_kind,
            reference=reference,
            facts=facts,
            confidence=confidence,
            excerpt_hash=digest,
            created_at=_utc(row.created_at),
        )

    async def list_evidence(
        self, project_id: str, source_kind: str | None = None, *, limit: int = 20, offset: int = 0
    ) -> list[EvidenceRecord]:
        statement = select(EvidenceItem).where(EvidenceItem.project_id == project_id)
        if source_kind is not None:
            statement = statement.where(EvidenceItem.source_kind == source_kind)
        rows = (
            await self.session.scalars(
                statement.order_by(
                    EvidenceItem.confidence.desc(), EvidenceItem.created_at.desc(), EvidenceItem.id.desc()
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [
            EvidenceRecord(
                id=row.id,
                project_id=row.project_id,
                source_kind=row.source_kind,
                reference=row.reference,
                facts=row.facts,
                confidence=row.confidence,
                excerpt_hash=row.excerpt_hash,
                created_at=_utc(row.created_at),
            )
            for row in rows
        ]

    # -- archaeology artifacts -------------------------------------------
    async def add_genome(self, project_id: str, payload: dict[str, Any], job_id: str | None = None) -> str:
        python_section = payload.get("python")
        os_section = payload.get("os")
        python: dict[str, Any] = python_section if isinstance(python_section, dict) else {}
        operating: dict[str, Any] = os_section if isinstance(os_section, dict) else {}
        row = Genome(
            id=_id("genome"),
            project_id=project_id,
            job_id=job_id,
            python_version=str(python.get("version")) if python.get("version") else None,
            os_image=str(operating.get("image")) if operating.get("image") else None,
            overall_confidence=float(payload.get("overall_confidence") or 0.0),
            payload=payload,
        )
        self.session.add(row)
        await self.flush()
        return row.id

    async def add_build_attempt(
        self,
        job_id: str,
        attempt: int,
        *,
        stage: str = "build",
        ok: bool = False,
        exit_code: int | None = None,
        output: str | None = None,
        error_fact: dict[str, Any] | None = None,
    ) -> str:
        row = BuildAttempt(
            id=_id("build"),
            job_id=job_id,
            attempt=attempt,
            stage=stage,
            ok=ok,
            exit_code=exit_code,
            output=output,
            error_fact=error_fact or {},
        )
        self.session.add(row)
        await self.flush()
        return row.id

    async def add_patch(
        self,
        job_id: str,
        entry: str,
        diff: str,
        *,
        accepted: bool = False,
        files_changed: int = 0,
        lines_changed: int = 0,
    ) -> str:
        row = Patch(
            id=_id("patch"),
            job_id=job_id,
            entry=entry,
            diff=diff,
            accepted=accepted,
            files_changed=files_changed,
            lines_changed=lines_changed,
        )
        self.session.add(row)
        await self.flush()
        return row.id

    async def add_behavior_run(
        self,
        job_id: str,
        *,
        plan_ref: str | None = None,
        cases: int = 0,
        compatibility: float | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        row = BehaviorRun(
            id=_id("behavior"),
            job_id=job_id,
            plan_ref=plan_ref,
            cases=cases,
            compatibility=compatibility,
            payload=payload or {},
        )
        self.session.add(row)
        await self.flush()
        return row.id

    async def add_fingerprint(
        self,
        project_id: str,
        payload: dict[str, Any],
        job_id: str | None = None,
        plan_ref: str | None = None,
    ) -> str:
        row = Fingerprint(
            id=_id("fingerprint"), project_id=project_id, job_id=job_id, plan_ref=plan_ref, payload=payload
        )
        self.session.add(row)
        await self.flush()
        return row.id

    async def count_evidence(self, project_id: str) -> int:
        found = await self.session.scalar(
            select(func.count()).select_from(EvidenceItem).where(EvidenceItem.project_id == project_id)
        )
        return int(found or 0)

    # -- capsules --------------------------------------------------------
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
        row = Capsule(
            id=capsule_id,
            project_id=project_id,
            job_id=job_id,
            user_id=user_id,
            object_key=object_key,
            sha256=sha256,
            size_bytes=size_bytes,
            manifest=manifest,
        )
        self.session.add(row)
        await self.flush()
        return CapsuleRecord(
            id=capsule_id,
            project_id=project_id,
            user_id=user_id,
            object_key=object_key,
            manifest=manifest,
            content=b"",
            sha256=sha256,
            created_at=_utc(row.created_at),
        )

    async def get_capsule(self, capsule_id: str) -> CapsuleRecord | None:
        row = await self.session.get(Capsule, capsule_id)
        if row is None:
            return None
        return self._to_capsule_record(row)

    async def list_capsules(self, project_id: str, *, include_deleted: bool = False) -> list[CapsuleRecord]:
        statement = select(Capsule).where(Capsule.project_id == project_id)
        if not include_deleted:
            statement = statement.where(Capsule.deleted_at.is_(None))
        rows = (await self.session.scalars(statement.order_by(Capsule.created_at.desc()))).all()
        return [self._to_capsule_record(row) for row in rows]

    async def soft_delete_capsule(self, capsule_id: str) -> None:
        await self.session.execute(update(Capsule).where(Capsule.id == capsule_id).values(deleted_at=_now()))

    # -- cost + audit ----------------------------------------------------
    async def record_llm_call(
        self,
        provider: str,
        model: str,
        usage: dict[str, Any],
        cost_usd: float,
        *,
        job_id: str | None = None,
        user_id: str | None = None,
        node: str = "",
        latency_ms: int | None = None,
    ) -> None:
        self.session.add(
            LLMCall(
                id=_id("llm_call"),
                job_id=job_id,
                user_id=user_id,
                provider=provider,
                model=model,
                node=node,
                usage=usage,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
        )
        await self.flush()

    async def llm_cost_by_provider(self, since: datetime) -> dict[str, float]:
        rows = (
            await self.session.execute(
                select(LLMCall.provider, func.coalesce(func.sum(LLMCall.cost_usd), 0))
                .where(LLMCall.created_at >= since)
                .group_by(LLMCall.provider)
            )
        ).all()
        return {provider: float(total) for provider, total in rows}

    async def append_audit(
        self,
        actor_id: str,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
        target_job_id: str | None = None,
    ) -> None:
        self.session.add(
            AdminAudit(
                id=_id("audit"),
                actor_id=actor_id,
                action=action,
                target_job_id=target_job_id,
                before=before,
                after=after,
            )
        )
        await self.flush()

    async def list_admin_jobs(self, status: str | None = None) -> list[JobRecord]:
        statement = select(Job)
        if status is not None:
            statement = statement.where(Job.status == status)
        rows = (await self.session.scalars(statement.order_by(Job.created_at.desc(), Job.id.desc()))).all()
        return [self._to_job_record(row) for row in rows]

    async def set_maintenance(self, enabled: bool) -> None:
        row = await self.session.get(RuntimeSetting, "maintenance")
        if row is None:
            self.session.add(RuntimeSetting(key="maintenance", value={"enabled": enabled}))
        else:
            await self.session.execute(
                update(RuntimeSetting).where(RuntimeSetting.key == "maintenance").values(value={"enabled": enabled})
            )
        await self.flush()

    async def is_maintenance(self) -> bool:
        row = await self.session.get(RuntimeSetting, "maintenance")
        return bool((row.value if row else {}).get("enabled", False))

    async def get_runtime_setting(self, key: str) -> dict[str, Any] | None:
        row = await self.session.get(RuntimeSetting, key)
        return dict(row.value or {}) if row is not None else None

    async def set_runtime_setting(self, key: str, value: dict[str, Any]) -> None:
        row = await self.session.get(RuntimeSetting, key)
        if row is None:
            self.session.add(RuntimeSetting(key=key, value=dict(value)))
        else:
            await self.session.execute(
                update(RuntimeSetting).where(RuntimeSetting.key == key).values(value=dict(value))
            )
        await self.flush()

    async def purge_user(self, user_id: str) -> None:
        await self.session.execute(delete(User).where(User.id == user_id))

    # -- mappers ---------------------------------------------------------
    @staticmethod
    def _to_user_record(row: User) -> UserRecord:
        return UserRecord(row.id, row.email, row.password_hash, row.role, _utc(row.created_at))

    @staticmethod
    def _to_api_key_record(row: ApiKey) -> ApiKeyRecord:
        return ApiKeyRecord(
            id=row.id,
            user_id=row.user_id,
            prefix=row.prefix,
            key_hash=row.key_hash,
            label=row.label,
            created_at=_utc(row.created_at),
            revoked_at=_utc(row.revoked_at) if row.revoked_at else None,
        )

    @staticmethod
    def _to_project_record(row: Project) -> ProjectRecord:
        return ProjectRecord(
            id=row.id,
            user_id=row.user_id,
            repo_url=row.repo_url,
            status=row.status,
            created_at=_utc(row.created_at),
            deleted_at=_utc(row.deleted_at) if row.deleted_at else None,
            metadata=dict(row.meta or {}),
        )

    @staticmethod
    def _to_job_record(row: Job) -> JobRecord:
        return JobRecord(
            id=row.id,
            project_id=row.project_id,
            user_id=row.user_id,
            status=row.status,
            created_at=_utc(row.created_at),
            cancel_requested=row.cancel_requested,
            admin_killed=row.admin_killed,
            metadata=dict(row.meta or {}),
        )

    def _to_capsule_record(self, row: Capsule) -> CapsuleRecord:
        return CapsuleRecord(
            id=row.id,
            project_id=row.project_id,
            user_id=row.user_id,
            object_key=row.object_key,
            manifest=dict(row.manifest or {}),
            content=b"",
            sha256=row.sha256,
            created_at=_utc(row.created_at),
            deleted_at=_utc(row.deleted_at) if row.deleted_at else None,
        )


__all__ = ["ControlPlaneRepository"]
