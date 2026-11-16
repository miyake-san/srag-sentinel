"""Application settings, validated once at boot (prefix ``SRAG_``)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Secrets use ``SecretStr`` so they never reach ``repr`` or logs."""

    model_config = SettingsConfigDict(
        env_prefix="SRAG_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    surreal_url: str = "ws://127.0.0.1:8000/rpc"
    surreal_namespace: str = "srag"
    surreal_data_database: str = "data"
    surreal_ingest_user: str = "ingest"
    surreal_ingest_password: SecretStr = SecretStr("")
    surreal_api_ro_user: str = "api_ro"
    surreal_api_ro_password: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (read once)."""
    return Settings()
