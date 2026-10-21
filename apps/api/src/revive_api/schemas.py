"""Pydantic API contracts shared by routers and OpenAPI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(..., examples=["internal"])
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str = Field(default="ok", pattern="^(ok)$")


class ReadyResponse(BaseModel):
    status: str
    components: dict[str, str] | None = None


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(RegisterRequest):
    pass


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class ApiKeyCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=128)


class ApiKeyResponse(BaseModel):
    id: str
    prefix: str
    key: str | None = None
    label: str | None = None
    created_at: datetime | None = None


class MeResponse(BaseModel):
    id: str
    email: str
    role: str
    created_at: datetime


class ProjectCreate(BaseModel):
    repository_url: str = Field(min_length=1, max_length=2048, alias="repo_url")
    repo_size_mb: int | None = Field(default=None, ge=0)

    model_config = {"populate_by_name": True}


class ProjectResponse(BaseModel):
    id: str
    user_id: str
    repo_url: str
    status: str
    created_at: datetime


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    next_cursor: str | None = None


class JobResponse(BaseModel):
    id: str
    project_id: str
    status: str
    created_at: datetime
    cancel_requested: bool = False


class JobListResponse(BaseModel):
    items: list[JobResponse]
    next_cursor: str | None = None


class ResurrectResponse(BaseModel):
    job_id: str
    status: str = "queued"


class ResurrectRequest(BaseModel):
    budget_usd: float | None = Field(default=None, ge=0, le=1000)
    timeout_seconds: float | None = Field(default=None, ge=1, le=86400)


class EvidenceResponse(BaseModel):
    id: str
    project_id: str
    source_kind: str
    reference: str
    facts: dict[str, Any]
    confidence: float
    excerpt_hash: str | None = None
    created_at: datetime


class EvidenceListResponse(BaseModel):
    items: list[EvidenceResponse]
    next_cursor: str | None = None


class CapsuleUploadRequest(BaseModel):
    manifest: dict[str, Any] = Field(default_factory=dict)
    content: str = ""
    sha256: str | None = None


class CapsuleResponse(BaseModel):
    id: str
    project_id: str
    object_key: str
    sha256: str
    manifest: dict[str, Any]
    created_at: datetime


class CapsuleListResponse(BaseModel):
    items: list[CapsuleResponse]
    next_cursor: str | None = None


class MaintenanceRequest(BaseModel):
    accepting_jobs: bool


class MaintenanceResponse(BaseModel):
    accepting_jobs: bool


class LlmSettingsRequest(BaseModel):
    provider: Literal["fake", "openai", "anthropic", "custom"]
    base_url: str = Field(default="", max_length=2048)
    model: str = Field(default="", max_length=256)
    api_key: str | None = Field(default=None, max_length=512)
    clear_api_key: bool = False
    reasoning_effort: Literal["low", "medium", "high"] | None = None


class LlmSettingsResponse(BaseModel):
    provider: str
    base_url: str = ""
    model: str = ""
    reasoning_effort: str | None = None
    api_key_set: bool = False
    api_key_hint: str | None = None
    source: str = "runtime"


class LlmTestResponse(BaseModel):
    ok: bool
    provider: str
    model: str = ""
    latency_ms: int | None = None
    detail: str | None = None


class EventResponse(BaseModel):
    id: str
    job_id: str
    type: str
    payload: dict[str, Any]
    created_at: str
