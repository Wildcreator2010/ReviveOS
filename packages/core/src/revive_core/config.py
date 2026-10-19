from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REVIVE_", env_file=".env", extra="ignore")
    env: str = "dev"
    database_url: str | None = None
    redis_url: str | None = None
    llm_reasoning_effort: str = "medium"

    @classmethod
    def load(cls) -> "Config":
        return cls()
