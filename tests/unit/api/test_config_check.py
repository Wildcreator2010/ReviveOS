import pytest
from revive_api.config_check import ConfigurationError, ensure_prod


def valid_environment(**overrides: str) -> dict[str, str]:
    values = {
        "REVIVE_ENV": "prod",
        "DATABASE_URL": "postgresql+asyncpg://revive:secret@postgres/revive",
        "REDIS_URL": "redis://:secret@redis:6379/0",
        "S3_ENDPOINT": "https://s3.example.test",
        "S3_ACCESS_KEY": "access",
        "S3_SECRET_KEY": "s" * 40,
        "S3_BUCKET": "revive",
        "REVIVE_LLM__API_KEY": "llm-token",
        "REVIVE_JWT__SECRET": "x" * 40,
        "REVIVE_WORKER__TOKEN": "w" * 40,
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


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("REVIVE_JWT__SECRET", "<REQUIRED_JWT_SECRET_32_BYTES_MINIMUM>"),
        ("REVIVE_WORKER__TOKEN", "<REQUIRED_WORKER_TOKEN>"),
        ("S3_ENDPOINT", "<REQUIRED_S3_ENDPOINT>"),
        ("S3_SECRET_KEY", "<REQUIRED_S3_SECRET_KEY>"),
        ("REVIVE_SECRETS__KEY", "<REQUIRED_SECRETS_KEY>"),
    ],
)
def test_production_rejects_unreplaced_template_placeholders(key: str, value: str) -> None:
    with pytest.raises(ConfigurationError, match=key):
        ensure_prod(valid_environment(**{key: value}))


def test_production_requires_a_high_entropy_worker_token() -> None:
    with pytest.raises(ConfigurationError, match="REVIVE_WORKER__TOKEN"):
        ensure_prod(valid_environment(REVIVE_WORKER__TOKEN="short-token"))


def test_production_rejects_short_secrets_key_when_present() -> None:
    with pytest.raises(ConfigurationError, match="REVIVE_SECRETS__KEY"):
        ensure_prod(valid_environment(REVIVE_SECRETS__KEY="too-short"))


def test_llm_key_may_be_configured_in_the_admin_settings_instead_of_env() -> None:
    values = valid_environment()
    values.pop("REVIVE_LLM__API_KEY")
    ensure_prod(values)
