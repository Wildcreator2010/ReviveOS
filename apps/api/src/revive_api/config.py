"""Configuration for the API control plane."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .config_check import ensure_prod


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    environment: str = "dev"
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    database_url: str = ""
    redis_url: str = ""
    llm_provider: str = "fake"
    llm_base_url: str = ""
    llm_model: str = ""
    jwt_secret: str = "dev-only-change-me"
    jwt_access_minutes: int = 15
    jwt_refresh_days: int = 7
    worker_token: str = "dev-worker-token"
    max_concurrent_jobs: int = 2
    max_jobs_per_day: int = 20
    max_repo_mb: int = 200
    login_failure_limit: int = 5
    login_lockout_minutes: int = 15
    capsule_presign_seconds: int = 60
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""
    s3_region: str = "us-east-1"

    @classmethod
    def from_env(cls) -> Config:
        if os.getenv("REVIVE_ENV", "dev").lower() in {"prod", "production"}:
            ensure_prod(os.environ)
        config = cls(
            environment=os.getenv("REVIVE_ENV", "dev"),
            cors_origins=_csv(os.getenv("REVIVE_CORS_ORIGINS", "http://localhost:3000")),
            cors_origin_regex=os.getenv("REVIVE_CORS_ORIGIN_REGEX", r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"),
            database_url=os.getenv("DATABASE_URL", ""),
            redis_url=os.getenv("REDIS_URL", ""),
            llm_provider=os.getenv("REVIVE_LLM__PROVIDER", "fake"),
            llm_base_url=os.getenv("REVIVE_LLM__BASE_URL", ""),
            llm_model=os.getenv("REVIVE_LLM__MODEL", ""),
            jwt_secret=os.getenv("REVIVE_JWT__SECRET", "dev-only-change-me"),
            jwt_access_minutes=_int_env("REVIVE_JWT__ACCESS_MINUTES", 15),
            jwt_refresh_days=_int_env("REVIVE_JWT__REFRESH_DAYS", 7),
            worker_token=os.getenv("REVIVE_WORKER__TOKEN", "dev-worker-token"),
            max_concurrent_jobs=_int_env("REVIVE_QUOTA__MAX_CONCURRENT_JOBS", 2),
            max_jobs_per_day=_int_env("REVIVE_QUOTA__MAX_JOBS_PER_DAY", 20),
            max_repo_mb=_int_env("REVIVE_QUOTA__MAX_REPO_MB", 200),
            login_failure_limit=_int_env("REVIVE_RATE__LOGIN_FAILURE_LIMIT", 5),
            login_lockout_minutes=_int_env("REVIVE_RATE__LOGIN_LOCKOUT_MINUTES", 15),
            capsule_presign_seconds=_int_env("REVIVE_STORAGE__PRESIGN_SECONDS", 60),
            s3_endpoint=os.getenv("S3_ENDPOINT", ""),
            s3_access_key=os.getenv("S3_ACCESS_KEY", ""),
            s3_secret_key=os.getenv("S3_SECRET_KEY", ""),
            s3_bucket=os.getenv("S3_BUCKET", ""),
            s3_region=os.getenv("S3_REGION", "us-east-1"),
        )
        if config.jwt_access_minutes < 1 or config.jwt_refresh_days < 1 or config.worker_token == "":
            raise ValueError("JWT lifetimes and worker token must be positive")
        return config
