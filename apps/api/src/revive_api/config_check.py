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
    "REVIVE_LLM__API_KEY",
    "REVIVE_JWT__SECRET",
    "REVIVE_WORKER__TOKEN",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
)
DEFAULT_SECRETS = frozenset({"change-me", "changeme", "secret", "dev-secret", "your-secret-here"})


class ConfigurationError(RuntimeError):
    """Production configuration is incomplete or unsafe."""


def ensure_prod(values: Mapping[str, str]) -> None:
    """Validate production settings without ever including secret values in errors."""
    missing = [key for key in REQUIRED_KEYS if not str(values.get(key, "")).strip()]
    invalid: list[str] = []
    jwt = str(values.get("REVIVE_JWT__SECRET", ""))
    if jwt and (len(jwt.encode("utf-8")) < 32 or jwt.lower() in DEFAULT_SECRETS):
        invalid.append("REVIVE_JWT__SECRET")
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
