"""Application settings, validated once at boot (prefix ``SRAG_``)."""

import re
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


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
    surreal_app_database: str = "app"

    # Bootstrap only (db init). The running application never uses root credentials.
    surreal_root_user: str = "root"
    surreal_root_password: SecretStr = SecretStr("")

    surreal_ingest_user: str = "ingest"
    surreal_ingest_password: SecretStr = SecretStr("")
    surreal_api_ro_user: str = "api_ro"
    surreal_api_ro_password: SecretStr = SecretStr("")
    surreal_api_rw_user: str = "api_rw"
    surreal_api_rw_password: SecretStr = SecretStr("")

    @field_validator(
        "surreal_namespace",
        "surreal_data_database",
        "surreal_app_database",
        "surreal_ingest_user",
        "surreal_api_ro_user",
        "surreal_api_rw_user",
    )
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        """Identifiers are interpolated into DEFINE statements, so they must be plain names."""
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("must match [a-z][a-z0-9_]{0,31}")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (read once)."""
    return Settings()
