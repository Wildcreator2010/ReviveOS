"""FastAPI application factory and control-plane HTTP surface."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import time
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from revive_agents.llm import FakeProvider, from_config, from_settings
from sse_starlette.sse import EventSourceResponse

from .config import Config
from .config_check import ConfigurationError
from .control_plane import ControlPlanePort, MemoryControlPlane
from .db.session import session_factory
from .db.uow import RequestControlPlane, SQLAlchemyUnitOfWorkMiddleware
from .deps import Probe, readiness_probes, run_probe
from .event_bus import HEARTBEAT_SECONDS, RedisEventBus, StoreEventBus, sse_frames
from .login_throttle import LoginThrottle, MemoryLoginThrottle, RedisLoginThrottle
from .middleware import RequestIdMiddleware
from .schemas import (
    ApiKeyCreateRequest,
    ApiKeyResponse,
    CapsuleListResponse,
    CapsuleResponse,
    CapsuleUploadRequest,
    EvidenceListResponse,
    EvidenceResponse,
    HealthResponse,
    JobListResponse,
    JobResponse,
    LlmSettingsRequest,
    LlmSettingsResponse,
    LlmTestResponse,
    LoginRequest,
    MaintenanceRequest,
    MaintenanceResponse,
    MeResponse,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ReadyResponse,
    RefreshRequest,
    RegisterRequest,
    ResurrectRequest,
    ResurrectResponse,
    TokenResponse,
)
from .secrets import decrypt_secret, encrypt_secret
from .security import decode_token, hash_password, issue_token, new_api_key
from .services.capsule_storage import CapsuleStorage, MemoryCapsuleStorage, S3CapsuleStorage
from .services.event_sink import SessionEventSink
from .store import CapsuleRecord, JobRecord, MemoryStore, ProjectRecord, UserRecord
from .worker import dispatch_job, revoke_job


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class ProjectUpdate(BaseModel):
    status: str | None = None
    metadata: dict[str, Any] | None = None


class JobCreate(BaseModel):
    project_id: str


class EvidenceCreate(BaseModel):
    source_kind: str
    reference: str
    facts: dict[str, Any] = {}
    confidence: float = 0.0
    excerpt: str | None = None


TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}


def _error_payload(request: Request, exc: ApiError) -> dict[str, Any]:
    error: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details is not None:
        error["details"] = exc.details
    request_id = getattr(request.state, "request_id", None) or request.scope.get("revive_request_id")
    if not request_id:
        # Exception handlers may receive a reconstructed Request from BaseHTTPMiddleware.
        request_id = f"req_{secrets.token_hex(16)}"
        request.state.request_id = request_id
    error["request_id"] = request_id
    return {"error": error}


def _project_response(project: ProjectRecord) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        user_id=project.user_id,
        repo_url=project.repo_url,
        status=project.status,
        created_at=project.created_at,
    )


def _job_response(job: JobRecord) -> JobResponse:
    return JobResponse(
        id=job.id,
        project_id=job.project_id,
        status=job.status,
        created_at=job.created_at,
        cancel_requested=job.cancel_requested,
    )


def _capsule_response(capsule: CapsuleRecord) -> CapsuleResponse:
    return CapsuleResponse(
        id=capsule.id,
        project_id=capsule.project_id,
        object_key=capsule.object_key,
        sha256=capsule.sha256,
        manifest=capsule.manifest,
        created_at=capsule.created_at,
    )


def _cursor_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = int(base64.urlsafe_b64decode(cursor.encode() + b"=" * (-len(cursor) % 4)).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ApiError(400, "invalid_cursor", "cursor is invalid") from exc
    if value < 0:
        raise ApiError(400, "invalid_cursor", "cursor is invalid")
    return value


def _next_cursor(offset: int, count: int, total: int) -> str | None:
    if offset + count >= total:
        return None
    return base64.urlsafe_b64encode(str(offset + count).encode()).decode().rstrip("=")


def _validate_repo_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() != "https" or host != "github.com" or parsed.username or parsed.password:
        raise ApiError(400, "repo_url_not_allowed", "repository URL must be an HTTPS github.com URL")
    if parsed.port not in (None, 443) or parsed.fragment or not parsed.path.strip("/"):
        raise ApiError(400, "repo_url_not_allowed", "repository URL must be an HTTPS github.com URL")
    # Outbound clones still pass through netguard at the worker egress seam.
    return f"https://github.com/{parsed.path.strip('/').removesuffix('.git')}"


def _repo_key(value: str) -> str:
    parsed = urlparse(value)
    return parsed.path.strip("/").removesuffix(".git").lower()


def _llm_settings_view(config: Config, stored: dict[str, Any] | None) -> LlmSettingsResponse:
    if stored:
        encrypted = str(stored.get("api_key_enc") or "")
        hint = str(stored.get("api_key_hint") or "") or (
            f"…{str(stored['api_key'])[-4:]}" if stored.get("api_key") else None
        )
        return LlmSettingsResponse(
            provider=str(stored.get("provider") or "fake"),
            base_url=str(stored.get("base_url") or ""),
            model=str(stored.get("model") or ""),
            reasoning_effort=str(stored["reasoning_effort"]) if stored.get("reasoning_effort") else None,
            api_key_set=bool(encrypted or stored.get("api_key")),
            api_key_hint=hint,
            source="runtime",
        )
    key = os.getenv("REVIVE_LLM__API_KEY", "")
    return LlmSettingsResponse(
        provider=config.llm_provider,
        base_url=config.llm_base_url,
        model=config.llm_model,
        reasoning_effort=os.getenv("REVIVE_LLM__REASONING_EFFORT") or None,
        api_key_set=bool(key),
        api_key_hint=f"…{key[-4:]}" if key else None,
        source="env",
    )


def _llm_audit_view(value: Mapping[str, Any] | None) -> dict[str, Any]:
    data = {key: item for key, item in (value or {}).items() if key not in {"api_key", "api_key_enc"}}
    data["api_key_set"] = bool((value or {}).get("api_key_enc") or (value or {}).get("api_key"))
    return data


T = TypeVar("T")
R = TypeVar("R", bound=Response)


def _paginate(items: list[T], limit: int, cursor: str | None) -> tuple[list[T], str | None]:
    if limit < 1 or limit > 100:
        raise ApiError(400, "invalid_pagination", "limit must be between 1 and 100")
    offset = _cursor_offset(cursor)
    selected = items[offset : offset + limit]
    return selected, _next_cursor(offset, len(selected), len(items))


async def _token_pair(app: FastAPI, user: UserRecord, family: str | None = None) -> TokenResponse:
    config: Config = app.state.config
    access = issue_token(
        user.id, config.jwt_secret, kind="access", expires=timedelta(minutes=config.jwt_access_minutes)
    )
    family_id = family or secrets.token_urlsafe(18)
    refresh = issue_token(
        user.id,
        config.jwt_secret,
        kind="refresh",
        expires=timedelta(days=config.jwt_refresh_days),
        family=family_id,
    )
    refresh_payload = decode_token(refresh, config.jwt_secret, kind="refresh")
    if refresh_payload and isinstance(refresh_payload.get("jti"), str):
        await app.state.control_plane.add_refresh_token(
            refresh_payload["jti"],
            family_id,
            user.id,
            datetime.now(UTC) + timedelta(days=config.jwt_refresh_days),
        )
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=config.jwt_access_minutes * 60)


async def _find_user_by_token(request: Request, *, role: str | None = None) -> UserRecord | None:
    port: ControlPlanePort = request.app.state.control_plane
    config: Config = request.app.state.config
    token = request.headers.get("X-Revive-Key")
    if token:
        key = await port.find_api_key(token)
        if key is not None:
            user = await port.get_user(key.user_id)
            if user and (role is None or user.role == role):
                return user
            if role is not None:
                raise ApiError(403, "forbidden", "insufficient role")
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        payload = decode_token(authorization[7:].strip(), config.jwt_secret, kind="access")
        if payload:
            user = await port.get_user(str(payload["sub"]))
            if user and (role is None or user.role == role):
                return user
            if role is not None:
                raise ApiError(403, "forbidden", "insufficient role")
    return None


async def _require_user(request: Request, *, role: str | None = None) -> UserRecord:
    user = await _find_user_by_token(request, role=role)
    if user is None:
        raise ApiError(401, "unauthorized", "authentication required")
    return user


def _require_owner(request: Request, user: UserRecord, project: ProjectRecord) -> None:
    if project.user_id != user.id or project.deleted_at is not None:
        raise ApiError(404, "not_found", "project not found")


async def _require_project(request: Request, project_id: str, user: UserRecord) -> ProjectRecord:
    project = await request.app.state.control_plane.get_project(project_id)
    if not project:
        raise ApiError(404, "not_found", "project not found")
    _require_owner(request, user, project)
    return project


async def _require_job(request: Request, job_id: str, user: UserRecord) -> JobRecord:
    job = await request.app.state.control_plane.get_job(job_id)
    if not job or job.user_id != user.id:
        raise ApiError(404, "not_found", "job not found")
    return job


def _repo_size_mb(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


async def _check_quota(request: Request, user: UserRecord, repo_size_mb: Any = None) -> None:
    port: ControlPlanePort = request.app.state.control_plane
    config: Config = request.app.state.config
    if await port.is_maintenance():
        raise ApiError(503, "maintenance", "new jobs are temporarily disabled")
    size = _repo_size_mb(repo_size_mb)
    if size is not None and size > config.max_repo_mb:
        raise ApiError(
            413, "repo_too_large", "repository exceeds the configured size limit", {"max_repo_mb": config.max_repo_mb}
        )
    if len(await port.active_jobs(user.id)) >= config.max_concurrent_jobs:
        raise ApiError(429, "quota_exceeded", "concurrent job quota exceeded", {"limit": config.max_concurrent_jobs})
    if await port.jobs_today(user.id) >= config.max_jobs_per_day:
        raise ApiError(429, "quota_exceeded", "daily job quota exceeded", {"limit": config.max_jobs_per_day})


def _retry_after(response: R, exc: ApiError) -> R:
    if exc.status_code == 429:
        response.headers["Retry-After"] = "60"
    return response


def _revoke_job(app: FastAPI, job_id: str) -> None:
    """Best-effort broker revoke for the inline dev executor.

    Production cancellation is cooperative: the worker's per-stage guard re-reads the
    persisted `cancel_requested` flag, so no broker handle is required.
    """

    if app.state.config.environment.lower() in {"prod", "production"}:
        return
    revoke_job(app.state.store, job_id)


def _dispatch_job(app: FastAPI, job_id: str) -> None:
    """Queue the job on Celery in production; never run user code inside the API."""

    if app.state.config.environment.lower() in {"prod", "production"}:
        from .tasks.pipeline import run_resurrection_job

        run_resurrection_job.delay(job_id)
        return
    dispatch_job(app.state.store, job_id)


def create_app(
    config: Config,
    probes: Mapping[str, Probe] | None = None,
    store: MemoryStore | None = None,
    events: StoreEventBus | None = None,
    login_throttle: LoginThrottle | None = None,
    control_plane: ControlPlanePort | None = None,
    engine_factory: Callable[[str], tuple[Any, Any]] = session_factory,
    capsule_storage: CapsuleStorage | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if config.database_url:
            engine, sessions = engine_factory(config.database_url)
            app.state.db_engine = engine
            app.state.db_sessions = sessions
            if production:
                if not config.redis_url:
                    raise ConfigurationError("production API requires REDIS_URL for the durable event bus")
                import redis.asyncio as aioredis

                app.state.redis_client = aioredis.from_url(config.redis_url)
                app.state.events = RedisEventBus(
                    SessionEventSink(sessions),
                    app.state.redis_client,
                )
                if app.state.login_throttle is None:
                    app.state.login_throttle = RedisLoginThrottle(app.state.redis_client)
        try:
            yield
        finally:
            redis_client = getattr(app.state, "redis_client", None)
            if redis_client is not None:
                await redis_client.aclose()
            elif isinstance(app.state.events, RedisEventBus):
                close = getattr(app.state.events.client, "aclose", None)
                if callable(close):
                    await close()
            engine = getattr(app.state, "db_engine", None)
            if engine is not None:
                await engine.dispose()

    app = FastAPI(title="ReviveOS API", version="v1", description="ReviveOS control-plane API", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_origin_regex=config.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = config
    production = config.environment.lower() in {"prod", "production"}
    app.state.store = store if store is not None else MemoryStore()
    if production:
        if control_plane is not None and not bool(getattr(control_plane, "durable", False)):
            raise ConfigurationError("production API requires a durable control-plane adapter")
        if control_plane is None:
            if not config.database_url:
                raise ConfigurationError("production API requires DATABASE_URL")
            control_plane = RequestControlPlane()
        if not isinstance(control_plane, RequestControlPlane):
            raise ConfigurationError("production API requires a request-scoped PostgreSQL control-plane factory")
        if not (config.s3_endpoint and config.s3_access_key and config.s3_secret_key and config.s3_bucket):
            raise ConfigurationError("production API requires S3_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET")
        app.state.control_plane = control_plane
    else:
        app.state.control_plane = control_plane or MemoryControlPlane(app.state.store)
    if login_throttle is not None and not login_throttle.durable and production:
        raise ConfigurationError("production API requires a durable login throttle adapter")
    # Production creates a Redis-backed throttle in lifespan, once the client exists.
    app.state.login_throttle = login_throttle if (login_throttle is not None or production) else MemoryLoginThrottle()
    if capsule_storage is None and production:
        capsule_storage = S3CapsuleStorage(
            endpoint=config.s3_endpoint,
            access_key=config.s3_access_key,
            secret_key=config.s3_secret_key,
            bucket=config.s3_bucket,
            region=config.s3_region,
        )
    app.state.capsule_storage = capsule_storage or MemoryCapsuleStorage()
    if production and not app.state.capsule_storage.durable:
        raise ConfigurationError("production API requires durable capsule object storage")
    if isinstance(app.state.control_plane, RequestControlPlane):
        app.add_middleware(
            SQLAlchemyUnitOfWorkMiddleware,
            sessions=lambda: getattr(app.state, "db_sessions", None),
            control_plane=app.state.control_plane,
        )
    if production and events is not None and not isinstance(events, RedisEventBus):
        raise ConfigurationError("production API requires RedisEventBus")
    app.state.events = events or StoreEventBus(app.state.store)
    app.state.readiness_probes = dict(probes or readiness_probes(config))

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        response = JSONResponse(status_code=exc.status_code, content=_error_payload(request, exc))
        return _retry_after(response, exc)

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        code = detail.pop("code", "http_error") if isinstance(detail, dict) else "http_error"
        message = detail.pop("message", str(exc.detail)) if isinstance(detail, dict) else str(exc.detail)
        error = ApiError(exc.status_code, code, message, detail or None)
        return await api_error_handler(request, error)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return await api_error_handler(
            request, ApiError(422, "validation_error", "request validation failed", {"errors": exc.errors()})
        )

    @app.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        from .metrics import metrics

        return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/readyz", response_model=ReadyResponse, tags=["health"])
    async def readyz() -> ReadyResponse:
        statuses = {
            name: ("ok" if await run_probe(probe) else "unavailable")
            for name, probe in app.state.readiness_probes.items()
        }
        if any(value != "ok" for value in statuses.values()):
            raise ApiError(
                503,
                "not_ready",
                "one or more dependencies are unavailable",
                {"detail": {"components": statuses}},
            )
        return ReadyResponse(status="ok", components=statuses)

    @app.get("/me", response_model=MeResponse, tags=["auth"])
    async def me(request: Request) -> MeResponse:
        user = await _require_user(request)
        return MeResponse(id=user.id, email=user.email, role=user.role, created_at=user.created_at)

    @app.post("/auth/register", response_model=TokenResponse, status_code=201, tags=["auth"])
    async def register(payload: RegisterRequest, request: Request) -> TokenResponse:
        try:
            from starlette.concurrency import run_in_threadpool

            digest = await run_in_threadpool(hash_password, payload.password)
            user = await app.state.control_plane.add_user(payload.email, digest)
        except ValueError as exc:
            raise ApiError(409, "email_in_use", "email is already registered") from exc
        return await _token_pair(app, user)

    @app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
    async def login(payload: LoginRequest, request: Request) -> TokenResponse:
        key = payload.email.strip().lower()
        retry_after = await app.state.login_throttle.check(key)
        if retry_after is not None:
            response = JSONResponse(
                status_code=429,
                content={"error": {"code": "login_rate_limited", "message": "login temporarily locked"}},
            )
            response.headers["Retry-After"] = str(retry_after)
            return response  # type: ignore[return-value]
        user = await app.state.control_plane.authenticate(payload.email, payload.password)
        if user is None:
            await app.state.login_throttle.failed(
                key, limit=config.login_failure_limit, lockout=config.login_lockout_minutes
            )
            raise ApiError(401, "invalid_credentials", "email or password is incorrect")
        await app.state.login_throttle.succeeded(key)
        return await _token_pair(app, user)

    @app.post("/auth/refresh", response_model=TokenResponse, tags=["auth"])
    async def refresh(payload: RefreshRequest, request: Request) -> TokenResponse:
        decoded = decode_token(payload.refresh_token, config.jwt_secret, kind="refresh")
        if not decoded or not isinstance(decoded.get("jti"), str):
            raise ApiError(401, "invalid_refresh_token", "refresh token is invalid or expired")
        port: ControlPlanePort = app.state.control_plane
        record = await port.get_refresh_token(decoded["jti"])
        family = str(decoded.get("family") or "")
        if not record or record.revoked or record.expires_at <= datetime.now(UTC):
            if family:
                await port.revoke_refresh_family(family)
            raise ApiError(401, "refresh_reuse_detected", "refresh token family has been revoked")
        if record.used:
            await port.revoke_refresh_family(record.family)
            raise ApiError(401, "refresh_reuse_detected", "refresh token reuse detected")
        if not await port.mark_refresh_token_used(record.jti):
            await port.revoke_refresh_family(record.family)
            raise ApiError(401, "refresh_reuse_detected", "refresh token reuse detected")
        user = await port.get_user(record.user_id)
        if not user:
            raise ApiError(401, "invalid_refresh_token", "refresh token is invalid")
        return await _token_pair(app, user, record.family)

    @app.post("/auth/logout", status_code=204, tags=["auth"])
    async def logout(payload: RefreshRequest, request: Request) -> Response:
        decoded = decode_token(payload.refresh_token, config.jwt_secret, kind="refresh")
        if decoded:
            family = str(decoded.get("family") or "")
            if family:
                await app.state.control_plane.revoke_refresh_family(family)
        return Response(status_code=204)

    @app.post("/auth/api-keys", response_model=ApiKeyResponse, status_code=201, tags=["auth"])
    async def create_api_key(payload: ApiKeyCreateRequest, request: Request) -> ApiKeyResponse:
        user = await _require_user(request)
        value, prefix, digest = new_api_key()
        record = await app.state.control_plane.add_api_key(
            user.id,
            prefix,
            digest,
            label=payload.label.strip() if payload.label else "",
        )
        return ApiKeyResponse(id=record.id, prefix=prefix, key=value, label=record.label, created_at=record.created_at)

    @app.get("/auth/api-keys", response_model=list[ApiKeyResponse], tags=["auth"])
    async def list_api_keys(request: Request) -> list[ApiKeyResponse]:
        user = await _require_user(request)
        keys = await app.state.control_plane.list_api_keys(user.id)
        return [
            ApiKeyResponse(id=key.id, prefix=key.prefix, label=key.label, created_at=key.created_at) for key in keys
        ]

    @app.delete("/auth/api-keys/{key_id}", status_code=204, tags=["auth"])
    async def revoke_api_key(key_id: str, request: Request) -> Response:
        user = await _require_user(request)
        if not await app.state.control_plane.revoke_api_key(key_id, user.id):
            raise ApiError(404, "not_found", "api key not found")
        return Response(status_code=204)

    @app.get("/projects", response_model=ProjectListResponse, tags=["projects"])
    async def list_projects(request: Request, limit: int = Query(20), cursor: str | None = None) -> ProjectListResponse:
        user = await _require_user(request)
        projects = await app.state.control_plane.list_projects(user.id)
        selected, next_cursor = _paginate(projects, limit, cursor)
        return ProjectListResponse(items=[_project_response(item) for item in selected], next_cursor=next_cursor)

    @app.post("/projects", response_model=ProjectResponse, status_code=201, tags=["projects"])
    async def create_project(payload: ProjectCreate, request: Request) -> ProjectResponse:
        # Validate before auth so legacy SSRF callers still receive a precise 400.
        repo_url = _validate_repo_url(payload.repository_url)
        user = await _require_user(request)
        repo_key = _repo_key(repo_url)
        for project in await app.state.control_plane.list_projects(user.id):
            if _repo_key(project.repo_url) == repo_key:
                raise ApiError(409, "project_exists", "project already exists", {"existing_id": project.id})
        if payload.repo_size_mb is not None and payload.repo_size_mb > config.max_repo_mb:
            raise ApiError(
                413,
                "repo_too_large",
                "repository exceeds the configured size limit",
                {"max_repo_mb": config.max_repo_mb},
            )
        project = await app.state.control_plane.add_project(user.id, repo_url, repo_key)
        if payload.repo_size_mb is not None:
            metadata = {**project.metadata, "repo_size_mb": payload.repo_size_mb}
            await app.state.control_plane.update_project(project.id, meta=metadata)
            project.metadata = metadata
        return _project_response(project)

    @app.get("/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
    async def get_project(project_id: str, request: Request) -> ProjectResponse:
        user = await _require_user(request)
        return _project_response(await _require_project(request, project_id, user))

    @app.patch("/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
    async def update_project(project_id: str, payload: ProjectUpdate, request: Request) -> ProjectResponse:
        user = await _require_user(request)
        project = await _require_project(request, project_id, user)
        fields: dict[str, Any] = {}
        if payload.status is not None:
            fields["status"] = payload.status
            project.status = payload.status
        if payload.metadata is not None:
            # Quota inputs are server-managed; a client must not overwrite them
            # through the generic metadata bag.
            incoming = {
                key: value for key, value in payload.metadata.items() if key not in {"repo_size_mb", "repo_key"}
            }
            if incoming:
                project.metadata.update(incoming)
                fields["meta"] = project.metadata
        if fields:
            await request.app.state.control_plane.update_project(project_id, **fields)
        return _project_response(project)

    @app.delete("/projects/{project_id}", status_code=204, tags=["projects"])
    async def delete_project(project_id: str, request: Request) -> Response:
        user = await _require_user(request)
        project = await _require_project(request, project_id, user)
        await request.app.state.control_plane.soft_delete_project(project_id)
        project.deleted_at = datetime.now(UTC)
        project.status = "deleted"
        return Response(status_code=204)

    @app.post("/projects/{project_id}/resurrect", response_model=ResurrectResponse, status_code=202, tags=["projects"])
    async def resurrect(
        project_id: str,
        request: Request,
        payload: ResurrectRequest | None = None,
    ) -> ResurrectResponse:
        user = await _require_user(request)
        project = await _require_project(request, project_id, user)
        await _check_quota(request, user, project.metadata.get("repo_size_mb"))
        pipeline: dict[str, Any] = {}
        if payload is not None:
            if payload.budget_usd is not None:
                pipeline["budget_usd"] = payload.budget_usd
            if payload.timeout_seconds is not None:
                pipeline["timeout_seconds"] = payload.timeout_seconds
        metadata: dict[str, Any] = {"repo_url": project.repo_url}
        if pipeline:
            metadata["pipeline"] = pipeline
        job = await app.state.control_plane.add_job(project.id, user.id, metadata)
        await app.state.control_plane.commit_current()
        await app.state.events.publish(job.id, "job.queued", {"status": "queued"})
        _dispatch_job(app, job.id)
        return ResurrectResponse(job_id=job.id)

    @app.post("/jobs", response_model=JobResponse, status_code=202, tags=["jobs"])
    async def create_job(payload: JobCreate, request: Request) -> JobResponse:
        user = await _require_user(request)
        project = await _require_project(request, payload.project_id, user)
        await _check_quota(request, user, project.metadata.get("repo_size_mb"))
        job = await app.state.control_plane.add_job(project.id, user.id, {"repo_url": project.repo_url})
        await app.state.control_plane.commit_current()
        await app.state.events.publish(job.id, "job.queued", {"status": "queued"})
        _dispatch_job(app, job.id)
        return _job_response(job)

    @app.get("/jobs", response_model=JobListResponse, tags=["jobs"])
    async def list_jobs(
        request: Request, project_id: str | None = None, limit: int = Query(20), cursor: str | None = None
    ) -> JobListResponse:
        user = await _require_user(request)
        jobs = await app.state.control_plane.list_jobs(user.id, project_id)
        selected, next_cursor = _paginate(jobs, limit, cursor)
        return JobListResponse(items=[_job_response(item) for item in selected], next_cursor=next_cursor)

    @app.get("/jobs/{job_id}", response_model=JobResponse, tags=["jobs"])
    async def get_job(job_id: str, request: Request) -> JobResponse:
        user = await _require_user(request)
        return _job_response(await _require_job(request, job_id, user))

    @app.post("/jobs/{job_id}/cancel", response_model=JobResponse, tags=["jobs"])
    async def cancel_job(job_id: str, request: Request) -> JobResponse:
        user = await _require_user(request)
        job = await _require_job(request, job_id, user)
        if job.status not in TERMINAL_JOB_STATES:
            await app.state.control_plane.update_job(job.id, cancel_requested=True, status="cancel_requested")
            job.cancel_requested = True
            job.status = "cancel_requested"
            _revoke_job(app, job.id)
        return _job_response(job)

    @app.get("/projects/{project_id}/evidence", response_model=EvidenceListResponse, tags=["evidence"])
    async def list_evidence(
        project_id: str,
        request: Request,
        source_kind: str | None = None,
        limit: int = Query(20),
        cursor: str | None = None,
    ) -> EvidenceListResponse:
        user = await _require_user(request)
        await _require_project(request, project_id, user)
        if limit < 1 or limit > 100:
            raise ApiError(400, "invalid_pagination", "limit must be between 1 and 100")
        offset = _cursor_offset(cursor)
        selected = await app.state.control_plane.list_evidence(project_id, source_kind, limit=limit + 1, offset=offset)
        has_more = len(selected) > limit
        selected = selected[:limit]
        next_cursor = _next_cursor(offset, limit, offset + len(selected) + (1 if has_more else 0)) if has_more else None
        return EvidenceListResponse(
            items=[EvidenceResponse(**item.__dict__) for item in selected],
            next_cursor=next_cursor,
        )

    @app.post("/projects/{project_id}/evidence", response_model=EvidenceResponse, status_code=201, tags=["evidence"])
    async def add_evidence(project_id: str, payload: EvidenceCreate, request: Request) -> EvidenceResponse:
        user = await _require_user(request)
        await _require_project(request, project_id, user)
        item = await app.state.control_plane.add_evidence(
            project_id, payload.source_kind, payload.reference, payload.facts, payload.confidence, payload.excerpt
        )
        return EvidenceResponse(**item.__dict__)

    @app.get("/projects/{project_id}/genome", tags=["artifacts"])
    async def get_genome(project_id: str, request: Request) -> dict[str, Any]:
        user = await _require_user(request)
        await _require_project(request, project_id, user)
        job = await app.state.control_plane.latest_job(project_id)
        return {"project_id": project_id, "genome": job.metadata.get("genome") if job else None}

    @app.get("/projects/{project_id}/builds", tags=["artifacts"])
    async def get_builds(project_id: str, request: Request) -> dict[str, Any]:
        user = await _require_user(request)
        await _require_project(request, project_id, user)
        job = await app.state.control_plane.latest_job(project_id)
        if job is None:
            return {"project_id": project_id, "items": []}
        items = [{"job_id": job.id, **build} for build in job.metadata.get("builds", [])]
        return {"project_id": project_id, "items": items}

    @app.get("/projects/{project_id}/patches", tags=["artifacts"])
    async def get_patches(project_id: str, request: Request) -> dict[str, Any]:
        user = await _require_user(request)
        await _require_project(request, project_id, user)
        job = await app.state.control_plane.latest_job(project_id)
        return {"project_id": project_id, "items": job.metadata.get("patches", []) if job else []}

    @app.get("/projects/{project_id}/behavior", tags=["artifacts"])
    async def get_behavior(project_id: str, request: Request) -> dict[str, Any]:
        user = await _require_user(request)
        await _require_project(request, project_id, user)
        job = await app.state.control_plane.latest_job(project_id)
        return {"project_id": project_id, "behavior": job.metadata.get("behavior") if job else None}

    @app.get("/projects/{project_id}/score", tags=["artifacts"])
    async def get_score(project_id: str, request: Request) -> dict[str, Any]:
        user = await _require_user(request)
        await _require_project(request, project_id, user)
        job = await app.state.control_plane.latest_job(project_id)
        return {"project_id": project_id, "score": job.metadata.get("score") if job else None}

    @app.get("/jobs/{job_id}/events", tags=["events"])
    async def list_events(job_id: str, request: Request, after: str | None = None) -> list[dict[str, Any]]:
        user = await _require_user(request)
        await _require_job(request, job_id, user)
        events = await app.state.control_plane.events_for_job(job_id, after)
        return [event.as_dict() for event in events]

    @app.get("/jobs/{job_id}/events/stream", tags=["events"])
    async def stream_events(
        job_id: str, request: Request, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")
    ) -> EventSourceResponse:
        user = await _require_user(request)
        await _require_job(request, job_id, user)
        # Framing, subscribe-before-history, heartbeat and the terminal rule all
        # live in event_bus.sse_frames so the writer and the reader share one encoder.
        return EventSourceResponse(sse_frames(app.state.events, job_id, last_event_id), ping=HEARTBEAT_SECONDS)

    @app.post("/jobs/{job_id}/capsule", response_model=CapsuleResponse, status_code=201, tags=["capsules"])
    async def upload_capsule(
        job_id: str,
        payload: CapsuleUploadRequest,
        request: Request,
        x_worker_token: str | None = Header(default=None),
    ) -> CapsuleResponse:
        supplied = (x_worker_token or "").encode("utf-8")
        expected = config.worker_token.encode("utf-8")
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise ApiError(401, "unauthorized", "worker authentication required")
        job = await app.state.control_plane.get_job(job_id)
        if not job:
            raise ApiError(404, "not_found", "job not found")
        project = await app.state.control_plane.get_project(job.project_id)
        if not project:
            raise ApiError(404, "not_found", "project not found")
        content = MemoryStore.decode_content(payload.content)
        digest = hashlib.sha256(content).hexdigest()
        declared = payload.sha256 or payload.manifest.get("sha256") or payload.manifest.get("digest")
        if declared and declared != digest:
            raise ApiError(
                422,
                "capsule_digest_mismatch",
                "capsule digest does not match manifest",
                {"expected": declared, "actual": digest},
            )
        capsule_id = f"rev_capsule_{secrets.token_hex(10)}"
        object_key = f"capsules/{project.user_id}/{capsule_id}.revive"
        await app.state.capsule_storage.put(object_key, content)
        try:
            capsule = await app.state.control_plane.add_capsule(
                capsule_id,
                project.id,
                project.user_id,
                payload.manifest,
                object_key,
                digest,
                len(content),
                job_id=job.id,
            )
        except Exception:
            # Never leave an unreferenced object behind when metadata persistence fails.
            await app.state.capsule_storage.delete(object_key)
            raise
        return _capsule_response(capsule)

    @app.get("/projects/{project_id}/capsules", response_model=CapsuleListResponse, tags=["capsules"])
    async def list_capsules(
        project_id: str, request: Request, limit: int = Query(20), cursor: str | None = None
    ) -> CapsuleListResponse:
        user = await _require_user(request)
        await _require_project(request, project_id, user)
        items = await app.state.control_plane.list_capsules(project_id)
        selected, next_cursor = _paginate(items, limit, cursor)
        return CapsuleListResponse(items=[_capsule_response(item) for item in selected], next_cursor=next_cursor)

    @app.get("/capsules/{capsule_id}", response_model=CapsuleResponse, tags=["capsules"])
    async def get_capsule(capsule_id: str, request: Request) -> CapsuleResponse:
        user = await _require_user(request)
        capsule = await app.state.control_plane.get_capsule(capsule_id)
        if not capsule or capsule.deleted_at is not None or capsule.user_id != user.id:
            raise ApiError(404, "not_found", "capsule not found")
        return _capsule_response(capsule)

    @app.get("/capsules/{capsule_id}/download", tags=["capsules"])
    async def download_capsule(capsule_id: str, request: Request) -> RedirectResponse:
        user = await _require_user(request)
        capsule = await app.state.control_plane.get_capsule(capsule_id)
        if not capsule or capsule.deleted_at is not None or capsule.user_id != user.id:
            raise ApiError(404, "not_found", "capsule not found")
        expires = int(datetime.now(UTC).timestamp()) + config.capsule_presign_seconds
        signature = hmac.new(config.jwt_secret.encode(), f"{capsule_id}:{expires}".encode(), hashlib.sha256).hexdigest()
        # Keep the content URL under /api/v1 so the production Caddy route proxies it.
        location = f"/api/v1/capsules/{quote(capsule_id)}/content?expires={expires}&signature={signature}"
        return RedirectResponse(url=location, status_code=302)

    @app.get("/capsules/{capsule_id}/content", include_in_schema=False)
    async def capsule_content(capsule_id: str, expires: int, signature: str) -> Response:
        if expires < int(datetime.now(UTC).timestamp()):
            raise ApiError(401, "download_expired", "download URL has expired")
        expected = hmac.new(config.jwt_secret.encode(), f"{capsule_id}:{expires}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ApiError(401, "invalid_download", "download URL is invalid")
        capsule = await app.state.control_plane.get_capsule(capsule_id)
        if not capsule or capsule.deleted_at is not None:
            raise ApiError(404, "not_found", "capsule not found")
        try:
            content = await app.state.capsule_storage.get(capsule.object_key)
        except FileNotFoundError as exc:
            raise ApiError(404, "not_found", "capsule object is missing") from exc
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{capsule_id}.revive"'},
        )

    @app.delete("/capsules/{capsule_id}", status_code=204, tags=["capsules"])
    async def delete_capsule(capsule_id: str, request: Request) -> Response:
        user = await _require_user(request)
        capsule = await app.state.control_plane.get_capsule(capsule_id)
        if not capsule or capsule.user_id != user.id:
            raise ApiError(404, "not_found", "capsule not found")
        await app.state.control_plane.soft_delete_capsule(capsule_id)
        return Response(status_code=204)

    @app.get("/admin/jobs", response_model=JobListResponse, tags=["admin"])
    async def admin_jobs(
        request: Request, status: str | None = None, limit: int = Query(20), cursor: str | None = None
    ) -> JobListResponse:
        await _require_user(request, role="admin")
        jobs = await request.app.state.control_plane.list_admin_jobs(status)
        selected, next_cursor = _paginate(jobs, limit, cursor)
        return JobListResponse(items=[_job_response(item) for item in selected], next_cursor=next_cursor)

    @app.post("/admin/jobs/{job_id}/kill", response_model=JobResponse, tags=["admin"])
    async def admin_kill(job_id: str, request: Request) -> JobResponse:
        admin = await _require_user(request, role="admin")
        job = await app.state.control_plane.get_job(job_id)
        if not job:
            raise ApiError(404, "not_found", "job not found")
        before = job.status
        await app.state.control_plane.update_job(job.id, cancel_requested=True, admin_killed=True, status="cancelled")
        job.cancel_requested = True
        job.admin_killed = True
        job.status = "cancelled"
        await app.state.events.publish(job.id, "job.failed", {"status": "cancelled", "reason": "admin_killed"})
        await app.state.control_plane.append_audit(
            admin.id,
            "kill_job",
            {"status": before},
            {"status": job.status},
            target_job_id=job_id,
        )
        return _job_response(job)

    @app.get("/admin/costs/daily", tags=["admin"])
    async def admin_costs(request: Request) -> dict[str, Any]:
        await _require_user(request, role="admin")
        midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        totals = await request.app.state.control_plane.llm_cost_by_provider(midnight)
        return {"date": datetime.now(UTC).date().isoformat(), "totals": totals}

    @app.post("/admin/maintenance", response_model=MaintenanceResponse, tags=["admin"])
    async def admin_maintenance(payload: MaintenanceRequest, request: Request) -> MaintenanceResponse:
        admin = await _require_user(request, role="admin")
        before = await request.app.state.control_plane.is_maintenance()
        await request.app.state.control_plane.set_maintenance(not payload.accepting_jobs)
        await request.app.state.control_plane.append_audit(
            admin.id,
            "maintenance",
            {"accepting_jobs": not before},
            {"accepting_jobs": payload.accepting_jobs},
        )
        return MaintenanceResponse(accepting_jobs=payload.accepting_jobs)

    @app.get("/admin/llm", response_model=LlmSettingsResponse, tags=["admin"])
    async def admin_llm_get(request: Request) -> LlmSettingsResponse:
        await _require_user(request, role="admin")
        stored = await request.app.state.control_plane.get_runtime_setting("llm")
        return _llm_settings_view(config, stored)

    @app.put("/admin/llm", response_model=LlmSettingsResponse, tags=["admin"])
    async def admin_llm_put(payload: LlmSettingsRequest, request: Request) -> LlmSettingsResponse:
        admin = await _require_user(request, role="admin")
        port: ControlPlanePort = request.app.state.control_plane
        current = await port.get_runtime_setting("llm") or {}
        provider = payload.provider
        base_url = payload.base_url.strip()
        model = payload.model.strip()
        encrypted_key = str(current.get("api_key_enc") or "")
        key_hint = str(current.get("api_key_hint") or "")
        if current.get("api_key"):
            # Migrate a legacy plaintext value on the next save.
            legacy = str(current["api_key"])
            encrypted_key = encrypt_secret(legacy)
            key_hint = f"…{legacy[-4:]}"
        if payload.clear_api_key:
            encrypted_key = ""
            key_hint = ""
        elif payload.api_key is not None and payload.api_key.strip():
            plain = payload.api_key.strip()
            encrypted_key = encrypt_secret(plain)
            key_hint = f"…{plain[-4:]}"

        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ApiError(400, "llm_settings_invalid", "base_url must be an http(s) URL")
        if provider != "fake":
            if not model:
                raise ApiError(400, "llm_settings_invalid", "model is required for this provider")
            if provider == "custom" and not base_url:
                raise ApiError(400, "llm_settings_invalid", "base_url is required for the custom provider")
            if not encrypted_key:
                raise ApiError(400, "llm_settings_invalid", "api_key is required for this provider")

        settings = {
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "reasoning_effort": payload.reasoning_effort,
            "api_key_enc": encrypted_key,
            "api_key_hint": key_hint,
        }
        await port.set_runtime_setting("llm", settings)
        await port.append_audit(admin.id, "llm_settings", _llm_audit_view(current), _llm_audit_view(settings))
        return _llm_settings_view(config, settings)

    @app.post("/admin/llm/test", response_model=LlmTestResponse, tags=["admin"])
    async def admin_llm_test(request: Request) -> LlmTestResponse:
        await _require_user(request, role="admin")
        stored = await request.app.state.control_plane.get_runtime_setting("llm")
        started = time.monotonic()
        try:
            provider_settings = dict(stored) if stored else None
            if provider_settings:
                encrypted = str(provider_settings.get("api_key_enc") or "")
                if encrypted:
                    provider_settings["api_key"] = decrypt_secret(encrypted)
            provider = from_settings(provider_settings) if provider_settings else from_config()
            if isinstance(provider, FakeProvider):
                return LlmTestResponse(
                    ok=True,
                    provider="fake",
                    model="",
                    latency_ms=0,
                    detail="fake provider (no network call)",
                )
            completion = await provider.complete(
                [{"role": "user", "content": "Reply with exactly: ok"}],
                max_tokens=8,
                timeout=20.0,
            )
            latency = int((time.monotonic() - started) * 1000)
            return LlmTestResponse(
                ok=True,
                provider=str(getattr(provider, "name", type(provider).__name__)),
                model=str(getattr(provider, "model", "") or ""),
                latency_ms=latency,
                detail=str(getattr(completion, "text", ""))[:120],
            )
        except Exception as exc:  # admin diagnostics must not fail the request shape
            return LlmTestResponse(
                ok=False,
                provider=str((stored or {}).get("provider") or config.llm_provider),
                model=str((stored or {}).get("model") or config.llm_model),
                latency_ms=int((time.monotonic() - started) * 1000),
                detail=f"{type(exc).__name__}: {str(exc)[:240]}",
            )

    # Keep the documented /api/v1 prefix while retaining the original local dev paths.
    # FastAPI's router object is assembled after route declarations below.
    from fastapi.routing import APIRoute

    root_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path not in {"/healthz", "/readyz", "/metrics"}
    ]
    for route in root_routes:
        if not route.path.startswith("/api/v1"):
            app.router.routes.append(
                APIRoute(
                    "/api/v1" + route.path,
                    route.endpoint,
                    methods=route.methods,
                    response_model=route.response_model,
                    status_code=route.status_code,
                    tags=route.tags,
                    dependencies=route.dependencies,
                    name=route.name + "_v1",
                    response_class=route.response_class,
                    summary=route.summary,
                    description=route.description,
                    operation_id=route.operation_id + "_v1" if route.operation_id else None,
                    response_model_include=route.response_model_include,
                    response_model_exclude=route.response_model_exclude,
                    response_model_by_alias=route.response_model_by_alias,
                    response_model_exclude_unset=route.response_model_exclude_unset,
                    response_model_exclude_defaults=route.response_model_exclude_defaults,
                    response_model_exclude_none=route.response_model_exclude_none,
                    include_in_schema=route.include_in_schema,
                )
            )

    return app


app = create_app(Config.from_env())
