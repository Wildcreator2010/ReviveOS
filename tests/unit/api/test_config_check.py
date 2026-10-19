import pytest
from revive_api.config_check import ConfigurationError, ensure_prod


def valid_environment(**overrides: str) -> dict[str, str]:
    values = {
        "REVIVE_ENV": "prod",
        "DATABASE_URL": "postgresql+asyncpg://revive:secret@postgres/revive",
        "REDIS_URL": "redis://:secret@redis:6379/0",
        "S3_ENDPOINT": "https://s3.example.test",
        "S3_ACCESS_KEY": "access",
        "S3_SECRET_KEY": "secret",
        "S3_BUCKET": "revive",
        "REVIVE_LLM__API_KEY": "llm-token",
        "REVIVE_JWT__SECRET": "x" * 40,
        "REVIVE_WORKER__TOKEN": "worker-token",
        "POSTGRES_PASSWORD": "a" * 64,
        "REDIS_PASSWORD": "b" * 64,
        "REVIVE_DEBUG_LLM": "false",
        "DEBUG": "false",
    }
    values.update(overrides)
    return values


def test_production_rejects_debug_for_both_production_spellings() -> None:
    for environment in ("prod", "production"):
        with pytest.raises(ConfigurationError, match="DEBUG"):
            ensure_prod(valid_environment(REVIVE_ENV=environment, DEBUG="true"))


def test_production_passwords_must_be_lowercase_hex() -> None:
    for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD"):
        with pytest.raises(ConfigurationError, match=key):
            ensure_prod(valid_environment(**{key: "special:@/password"}))


def test_valid_production_environment_passes() -> None:
    ensure_prod(valid_environment())
