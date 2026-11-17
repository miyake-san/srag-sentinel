"""Explicit provider factory (ADR 0007).

Cloud: Anthropic, Gemini, OpenRouter, Groq, NVIDIA NIM. Local or self-hosted: Ollama and any
OpenAI-compatible server (Unsloth, vLLM, llama.cpp...). Provider packages are imported lazily so
only the active provider's extra is required, and only that provider's key is read. No model id
is hardcoded except the Anthropic default in :mod:`srag_sentinel.settings`.
"""

import importlib
from dataclasses import dataclass
from typing import Any

from srag_sentinel.llm.fallback import FallbackStructuredModel
from srag_sentinel.llm.langchain_adapter import LangChainStructuredModel
from srag_sentinel.llm.ports import StructuredModel
from srag_sentinel.settings import Provider, Settings

PLACEHOLDER_KEY = "not-needed"  # local OpenAI-compatible servers accept any key


class LLMConfigError(ValueError):
    """The LLM configuration is incomplete or the provider package is not installed."""


@dataclass(frozen=True)
class ProviderSpec:
    """How to build one provider's chat model."""

    module: str
    class_name: str
    extra: str | None  # pip extra that installs the package (None = always installed)
    key_env: str | None = None  # variable users set; None = the provider takes no key
    key_field: str | None = None  # Settings field holding the key
    key_optional: bool = False  # local servers: a placeholder key is sent when none is set
    base_url_field: str | None = None  # Settings field holding the endpoint
    base_url_env: str | None = None  # variable users set (for error messages)
    base_url_required: bool = False
    sends_key: bool = True  # False for clients that have no api_key argument (Ollama)


PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        "langchain_anthropic", "ChatAnthropic", None, "ANTHROPIC_API_KEY", "anthropic_api_key"
    ),
    "google_genai": ProviderSpec(
        "langchain_google_genai",
        "ChatGoogleGenerativeAI",
        "google",
        "GOOGLE_API_KEY",
        "google_api_key",
    ),
    "nvidia": ProviderSpec(
        "langchain_nvidia_ai_endpoints",
        "ChatNVIDIA",
        "nvidia",
        "NVIDIA_API_KEY",
        "nvidia_api_key",
        base_url_field="nvidia_base_url",
        base_url_env="SRAG_NVIDIA_BASE_URL",
    ),
    "openrouter": ProviderSpec(
        "langchain_openrouter",
        "ChatOpenRouter",
        "openrouter",
        "OPENROUTER_API_KEY",
        "openrouter_api_key",
    ),
    "groq": ProviderSpec("langchain_groq", "ChatGroq", "groq", "GROQ_API_KEY", "groq_api_key"),
    "unsloth": ProviderSpec(
        "langchain_openai",
        "ChatOpenAI",
        "unsloth",
        "UNSLOTH_API_KEY",
        "unsloth_api_key",
        key_optional=True,
        base_url_field="unsloth_base_url",
        base_url_env="SRAG_UNSLOTH_BASE_URL",
        base_url_required=True,
    ),
    "ollama": ProviderSpec(
        "langchain_ollama",
        "ChatOllama",
        "ollama",
        base_url_field="ollama_base_url",
        base_url_env="SRAG_OLLAMA_BASE_URL",
        sends_key=False,
    ),
}


def _options(
    settings: Settings, provider: Provider, spec: ProviderSpec, model: str
) -> dict[str, Any]:
    options: dict[str, Any] = {"model": model, "temperature": 0}
    if spec.sends_key:
        key = ""
        if spec.key_field is not None:
            key = getattr(settings, spec.key_field).get_secret_value()
        if not key and not spec.key_optional:
            raise LLMConfigError(f"{provider}: missing API key ({spec.key_env})")
        options["api_key"] = key or PLACEHOLDER_KEY
    if spec.base_url_field is not None:
        url = getattr(settings, spec.base_url_field)
        if not url and spec.base_url_required:
            raise LLMConfigError(f"{provider}: missing endpoint ({spec.base_url_env})")
        if url:
            options["base_url"] = url
    return options


def _structured_method(settings: Settings, provider: Provider) -> str | None:
    """Anthropic needs ``json_schema`` (forced tool calling is unsupported on recent models)."""
    if settings.llm_structured_method:
        return settings.llm_structured_method
    return "json_schema" if provider == "anthropic" else None


def build_structured_model(
    settings: Settings, *, provider: Provider, model: str
) -> StructuredModel:
    """Build a structured-output model for ``provider``/``model`` (temperature 0, no tools).

    Fails fast with a clear message when the model id, API key or endpoint is missing or the
    provider package (an optional extra) is not installed.
    """
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise LLMConfigError(f"unknown provider {provider!r}; use one of {sorted(PROVIDERS)}")
    if not model.strip():
        raise LLMConfigError(f"{provider}: model id is required")
    options = _options(settings, provider, spec, model)

    try:
        module = importlib.import_module(spec.module)
    except ImportError as error:
        hint = f"uv sync --extra {spec.extra}" if spec.extra else "uv sync"
        raise LLMConfigError(
            f"{provider}: package {spec.module!r} not installed ({hint})"
        ) from error

    chat_model = getattr(module, spec.class_name)(**options)
    return LangChainStructuredModel(
        chat_model,
        name=f"{provider}:{model}",
        structured_method=_structured_method(settings, provider),
    )


DEFAULT_PRIORITY = ("openrouter", "groq", "nvidia", "unsloth", "google_genai", "ollama")


def parse_priority(text: str) -> list[tuple[Provider, str]]:
    """Parse ``provider=model,provider=model`` (order = priority) and validate every entry."""
    entries: list[tuple[Provider, str]] = []
    for raw in text.split(","):
        item = raw.strip()
        if not item:
            continue
        provider, separator, model = item.partition("=")
        provider, model = provider.strip(), model.strip()
        if not separator or not model:
            raise LLMConfigError(f"priority entry {item!r} must look like provider=model")
        if provider not in PROVIDERS:
            raise LLMConfigError(f"unknown provider {provider!r} in the priority list")
        entries.append((provider, model))  # type: ignore[arg-type]
    if not entries:
        raise LLMConfigError("the priority list is empty")
    return entries


def build_prioritized_model(
    settings: Settings, entries: list[tuple[Provider, str]]
) -> StructuredModel:
    """Build a failover chain in the given order, skipping providers that are not configured.

    A provider without a key, endpoint or installed package is skipped (and named in the error if
    nothing at all is usable); configuration problems never expose a secret value.
    """
    usable: list[StructuredModel] = []
    skipped: list[str] = []
    for provider, model in entries:
        try:
            usable.append(build_structured_model(settings, provider=provider, model=model))
        except LLMConfigError as error:
            skipped.append(str(error))
    if not usable:
        raise LLMConfigError("no provider in the priority list is usable: " + "; ".join(skipped))
    return usable[0] if len(usable) == 1 else FallbackStructuredModel(usable)


def build_large_model(settings: Settings) -> StructuredModel:
    """Build the main (``large``) tier: the priority chain when set, else the primary provider."""
    if settings.llm_priority:
        return build_prioritized_model(settings, parse_priority(settings.llm_priority))
    return build_structured_model(
        settings, provider=settings.llm_provider, model=settings.llm_model
    )
