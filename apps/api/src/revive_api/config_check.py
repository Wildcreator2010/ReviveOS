"""Fail-closed production configuration validation."""

from __future__ import annotations

from collections.abc import Mapping

REQUIRED_KEYS = (
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
    "DATABASE_URL",
    "REDIS_URL",
    "REVIVE_JWT__SECRET",
    "REVIVE_WORKER__TOKEN",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
)
DEFAULT_SECRETS = frozenset({"change-me", "changeme", "secret", "dev-secret", "your-secret-here"})
PLACEHOLDER_MARKERS = ("<required_", "change_me", "changeme", "your-", "replace-me")
MIN_SECRET_BYTES = 32
MIN_S3_SECRET_BYTES = 16


class ConfigurationError(RuntimeError):
    """Production configuration is incomplete or unsafe."""


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        not lowered
        or lowered.startswith("<")
        and lowered.endswith(">")
        or any(marker in lowered for marker in PLACEHOLDER_MARKERS)
    )


def ensure_prod(values: Mapping[str, str]) -> None:
    """Validate production settings without ever including secret values in errors."""
    missing = [key for key in REQUIRED_KEYS if not str(values.get(key, "")).strip()]
    invalid: list[str] = []
    for key in REQUIRED_KEYS:
        value = str(values.get(key, "")).strip()
        if value and _is_placeholder(value):
            invalid.append(key)
    jwt = str(values.get("REVIVE_JWT__SECRET", ""))
    if jwt and (len(jwt.encode("utf-8")) < MIN_SECRET_BYTES or jwt.lower() in DEFAULT_SECRETS):
        invalid.append("REVIVE_JWT__SECRET")
    worker_token = str(values.get("REVIVE_WORKER__TOKEN", ""))
    if worker_token and (
        len(worker_token.encode("utf-8")) < MIN_SECRET_BYTES or worker_token.lower() in DEFAULT_SECRETS
    ):
        invalid.append("REVIVE_WORKER__TOKEN")
    secrets_key = str(values.get("REVIVE_SECRETS__KEY", ""))
    if secrets_key and (len(secrets_key.encode("utf-8")) < MIN_SECRET_BYTES or _is_placeholder(secrets_key)):
        invalid.append("REVIVE_SECRETS__KEY")
    s3_secret = str(values.get("S3_SECRET_KEY", ""))
    if s3_secret and len(s3_secret.encode("utf-8")) < MIN_S3_SECRET_BYTES:
        invalid.append("S3_SECRET_KEY")
    for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD"):
        secret = str(values.get(key, ""))
        if secret and (len(secret) != 64 or any(char not in "0123456789abcdef" for char in secret)):
            invalid.append(key)
    if str(values.get("REVIVE_ENV", "dev")).lower() in {"prod", "production"}:
        for key in ("REVIVE_DEBUG_LLM", "DEBUG"):
            if str(values.get(key, "")).lower() in {"1", "true", "yes", "on"}:
                invalid.append(key)
    keys = sorted(set(missing + invalid))
    if keys:
        raise ConfigurationError("invalid production configuration keys: " + ", ".join(keys))


__all__ = ["ConfigurationError", "REQUIRED_KEYS", "ensure_prod"]
