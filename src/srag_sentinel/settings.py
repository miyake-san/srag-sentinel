"""Application settings, validated once at boot (prefix ``SRAG_``)."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

Provider = Literal["anthropic", "google_genai", "nvidia", "openrouter", "groq", "unsloth", "ollama"]
StructuredMethod = Literal["function_calling", "json_schema", "json_mode"]
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"


class Settings(BaseSettings):
    """Runtime configuration. Secrets use ``SecretStr`` so they never reach ``repr`` or logs."""

    model_config = SettingsConfigDict(
        env_prefix="SRAG_",
        env_file=".env",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
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

    # Audit trail (docs/specs/05): the app writes as a record-access user, never as a system user.
    surreal_audit_database: str = "audit"
    surreal_audit_writer_name: str = "app"
    surreal_audit_writer_password: SecretStr = SecretStr("")
    surreal_audit_reader_user: str = "audit_reader"
    surreal_audit_reader_password: SecretStr = SecretStr("")

    # OTLP/HTTP collector base URL (the standard OpenTelemetry variable); unset = no export.
    otel_endpoint: str | None = Field(default=None, validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")

    # Where rendered reports (HTML/JSON/PDF) are kept, one folder per run id.
    reports_dir: Path = Path("reports")

    # Knowledge graph (docs/specs/07): its own database; only `kg_writer` writes, `api_ro` reads.
    surreal_kg_database: str = "kg"
    surreal_kg_writer_user: str = "kg_writer"
    surreal_kg_writer_password: SecretStr = SecretStr("")
    kg_enabled: bool = True
    kg_top_k: int = Field(default=12, ge=1, le=50)
    kg_max_hops: int = Field(default=2, ge=1, le=3)
    kg_claim_ttl_days: int = Field(default=30, ge=1, le=365)

    # LLM tiers (docs/specs/03 §4 and 08 §2). `large` is the main model; `small` and `judge`
    # are optional and fall back to `large` when unset.
    llm_provider: Provider = "anthropic"
    llm_model: str = DEFAULT_ANTHROPIC_MODEL
    # Ordered failover for the large tier: "openrouter=<model>,groq=<model>,nvidia=<model>,..."
    # First usable entry serves; the next is tried when it fails. Overrides llm_provider/model.
    llm_priority: str | None = None
    router_small_provider: Provider | None = None
    router_small_model: str | None = None
    router_judge_provider: Provider | None = None
    router_judge_model: str | None = None
    nvidia_base_url: str | None = Field(default=None, description="self-hosted NIM endpoint")
    # Local or self-hosted servers. Unsloth (or vLLM, llama.cpp...) speaks the OpenAI protocol:
    # set its endpoint, e.g. http://localhost:8888/v1. Ollama defaults to its usual port.
    unsloth_base_url: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    # Override how structured output is requested for every tier (provider default when unset).
    llm_structured_method: StructuredMethod | None = None

    # Provider API keys use each vendor's standard variable name, never the SRAG_ prefix.
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="ANTHROPIC_API_KEY"
    )
    google_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    nvidia_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="NVIDIA_API_KEY")
    openrouter_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="OPENROUTER_API_KEY"
    )
    groq_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GROQ_API_KEY")
    unsloth_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="UNSLOTH_API_KEY")

    @field_validator(
        "surreal_namespace",
        "surreal_data_database",
        "surreal_app_database",
        "surreal_ingest_user",
        "surreal_api_ro_user",
        "surreal_api_rw_user",
        "surreal_audit_database",
        "surreal_audit_reader_user",
        "surreal_kg_database",
        "surreal_kg_writer_user",
    )
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        """Identifiers are interpolated into DEFINE statements, so they must be plain names."""
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("must match [a-z][a-z0-9_]{0,31}")
        return value

    @model_validator(mode="after")
    def _tiers_are_complete(self) -> Settings:
        """A tier is either fully configured (provider and model) or not at all."""
        for tier, provider, model in (
            ("router_small", self.router_small_provider, self.router_small_model),
            ("router_judge", self.router_judge_provider, self.router_judge_model),
        ):
            if (provider is None) != (model is None):
                raise ValueError(f"{tier}: set both provider and model, or neither")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (read once)."""
    return Settings()
