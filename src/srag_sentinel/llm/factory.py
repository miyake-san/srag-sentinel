"""Explicit provider factory (ADR 0007): Anthropic, Gemini, NVIDIA NIM and OpenRouter.

Provider packages are imported lazily so only the active provider's extra is required, and
only that provider's API key is read. No model id is hardcoded except the Anthropic default
in :mod:`srag_sentinel.settings`.
"""

import importlib
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from srag_sentinel.llm.langchain_adapter import LangChainStructuredModel
from srag_sentinel.llm.ports import StructuredModel
from srag_sentinel.settings import Provider, Settings


class LLMConfigError(ValueError):
    """The LLM configuration is incomplete or the provider package is not installed."""


@dataclass(frozen=True)
class ProviderSpec:
    """How to build one provider's chat model."""

    module: str
    class_name: str
    extra: str | None  # pip extra that installs the package (None = always installed)
    key_env: str  # environment variable users set (for error messages)


PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec("langchain_anthropic", "ChatAnthropic", None, "ANTHROPIC_API_KEY"),
    "google_genai": ProviderSpec(
        "langchain_google_genai", "ChatGoogleGenerativeAI", "google", "GOOGLE_API_KEY"
    ),
    "nvidia": ProviderSpec(
        "langchain_nvidia_ai_endpoints", "ChatNVIDIA", "nvidia", "NVIDIA_API_KEY"
    ),
    "openrouter": ProviderSpec(
        "langchain_openrouter", "ChatOpenRouter", "openrouter", "OPENROUTER_API_KEY"
    ),
}


def _api_key(settings: Settings, provider: Provider) -> SecretStr:
    return {
        "anthropic": settings.anthropic_api_key,
        "google_genai": settings.google_api_key,
        "nvidia": settings.nvidia_api_key,
        "openrouter": settings.openrouter_api_key,
    }[provider]


def build_structured_model(
    settings: Settings, *, provider: Provider, model: str
) -> StructuredModel:
    """Build a structured-output model for ``provider``/``model`` (temperature 0, no tools).

    Fails fast with a clear message when the model id or API key is missing or the provider
    package (an optional extra) is not installed.
    """
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise LLMConfigError(f"unknown provider {provider!r}; use one of {sorted(PROVIDERS)}")
    if not model.strip():
        raise LLMConfigError(f"{provider}: model id is required")
    key = _api_key(settings, provider).get_secret_value()
    if not key:
        raise LLMConfigError(f"{provider}: missing API key ({spec.key_env})")

    try:
        module = importlib.import_module(spec.module)
    except ImportError as error:
        hint = f"uv sync --extra {spec.extra}" if spec.extra else "uv sync"
        raise LLMConfigError(
            f"{provider}: package {spec.module!r} not installed ({hint})"
        ) from error

    options: dict[str, Any] = {"model": model, "temperature": 0, "api_key": key}
    if provider == "nvidia" and settings.nvidia_base_url:
        options["base_url"] = settings.nvidia_base_url
    chat_model = getattr(module, spec.class_name)(**options)
    return LangChainStructuredModel(chat_model, name=f"{provider}:{model}")


def build_large_model(settings: Settings) -> StructuredModel:
    """Build the main (``large``) tier model from the primary LLM settings."""
    return build_structured_model(
        settings, provider=settings.llm_provider, model=settings.llm_model
    )
