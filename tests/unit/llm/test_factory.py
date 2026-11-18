from typing import Any

import pytest
from pydantic import ValidationError

from srag_sentinel.llm import factory
from srag_sentinel.llm.factory import (
    DEFAULT_PRIORITY,
    PROVIDERS,
    LLMConfigError,
    build_large_model,
    build_prioritized_model,
    build_structured_model,
    parse_priority,
)
from srag_sentinel.settings import Settings


class StubChat:
    """Stands in for a provider chat class; records constructor kwargs."""

    instances: list[StubChat] = []  # noqa: RUF012 - test double

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        StubChat.instances.append(self)

    def with_structured_output(self, schema: type) -> Any:
        return self


class StubModule:
    def __init__(self, class_name: str) -> None:
        setattr(self, class_name, StubChat)


@pytest.fixture(autouse=True)
def stub_provider_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    StubChat.instances.clear()
    modules = {spec.module: StubModule(spec.class_name) for spec in PROVIDERS.values()}

    def fake_import(name: str) -> Any:
        return modules[name]

    monkeypatch.setattr(factory.importlib, "import_module", fake_import)


def settings(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize(
    ("provider", "key_field", "extra_kwargs"),
    [
        ("anthropic", "anthropic_api_key", {}),
        ("google_genai", "google_api_key", {}),
        ("nvidia", "nvidia_api_key", {}),
        ("openrouter", "openrouter_api_key", {}),
    ],
)
def test_each_provider_is_built_with_temperature_zero_model_and_key(
    provider: str, key_field: str, extra_kwargs: dict[str, Any]
) -> None:
    config = settings(**{key_field: "k-123"})

    built = build_structured_model(config, provider=provider, model="some-model")  # type: ignore[arg-type]

    kwargs = StubChat.instances[-1].kwargs
    assert kwargs == {"model": "some-model", "temperature": 0, "api_key": "k-123"}
    assert built.name == f"{provider}:some-model"


def test_nvidia_can_point_at_a_self_hosted_nim() -> None:
    config = settings(nvidia_api_key="k", nvidia_base_url="http://nim.local:8000/v1")

    build_structured_model(config, provider="nvidia", model="m")

    assert StubChat.instances[-1].kwargs["base_url"] == "http://nim.local:8000/v1"


def test_only_the_active_providers_key_is_required() -> None:
    config = settings(openrouter_api_key="only-this")

    build_structured_model(config, provider="openrouter", model="vendor/model")  # no error


def test_a_missing_key_names_the_variable_to_set() -> None:
    with pytest.raises(LLMConfigError, match="GOOGLE_API_KEY"):
        build_structured_model(settings(), provider="google_genai", model="m")


def test_an_empty_model_id_is_rejected() -> None:
    with pytest.raises(LLMConfigError, match="model id"):
        build_structured_model(settings(anthropic_api_key="k"), provider="anthropic", model=" ")


def test_the_example_placeholder_is_not_a_model_id() -> None:
    with pytest.raises(LLMConfigError, match="placeholder"):
        build_structured_model(settings(groq_api_key="k"), provider="groq", model="<model>")


def test_an_unknown_provider_is_rejected() -> None:
    with pytest.raises(LLMConfigError, match="unknown provider"):
        build_structured_model(settings(), provider="nope", model="m")  # type: ignore[arg-type]


def test_a_missing_optional_package_points_to_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_import(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(factory.importlib, "import_module", failing_import)

    with pytest.raises(LLMConfigError, match="--extra nvidia"):
        build_structured_model(settings(nvidia_api_key="k"), provider="nvidia", model="m")


def test_the_large_tier_comes_from_the_primary_settings() -> None:
    config = settings(llm_provider="anthropic", llm_model="my-large", anthropic_api_key="k")

    assert build_large_model(config).name == "anthropic:my-large"


def test_default_model_is_the_anthropic_default() -> None:
    assert settings().llm_provider == "anthropic"
    assert settings().llm_model == "claude-sonnet-5-5"


def test_api_keys_use_the_vendor_variable_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-from-env")

    loaded = Settings(_env_file=None)

    assert loaded.anthropic_api_key.get_secret_value() == "sk-from-env"
    assert loaded.google_api_key.get_secret_value() == "gem-from-env"
    assert "sk-from-env" not in repr(loaded)


@pytest.mark.parametrize(
    "tier",
    [
        {"router_small_provider": "nvidia"},
        {"router_small_model": "m"},
        {"router_judge_provider": "anthropic"},
        {"router_judge_model": "m"},
    ],
)
def test_a_tier_needs_both_provider_and_model(tier: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="both provider and model"):
        settings(**tier)


def test_a_fully_configured_small_tier_is_accepted() -> None:
    config = settings(router_small_provider="nvidia", router_small_model="small-model")

    assert config.router_small_model == "small-model"


@pytest.mark.parametrize(
    ("provider", "settings_kwargs", "expected"),
    [
        ("groq", {"groq_api_key": "g-1"}, {"model": "m", "temperature": 0, "api_key": "g-1"}),
        (
            "unsloth",
            {"unsloth_base_url": "http://localhost:8888/v1"},
            {
                "model": "m",
                "temperature": 0,
                "api_key": "not-needed",
                "base_url": "http://localhost:8888/v1",
            },
        ),
        (
            "unsloth",
            {"unsloth_base_url": "http://h/v1", "unsloth_api_key": "u-1"},
            {"model": "m", "temperature": 0, "api_key": "u-1", "base_url": "http://h/v1"},
        ),
        ("ollama", {}, {"model": "m", "temperature": 0, "base_url": "http://localhost:11434"}),
        (
            "ollama",
            {"ollama_base_url": "http://host.docker.internal:11434"},
            {"model": "m", "temperature": 0, "base_url": "http://host.docker.internal:11434"},
        ),
    ],
)
def test_groq_unsloth_and_ollama_are_built_with_their_own_options(
    provider: str, settings_kwargs: dict[str, Any], expected: dict[str, Any]
) -> None:
    build_structured_model(settings(**settings_kwargs), provider=provider, model="m")  # type: ignore[arg-type]

    assert StubChat.instances[-1].kwargs == expected


def test_unsloth_needs_an_endpoint_and_ollama_needs_no_key() -> None:
    with pytest.raises(LLMConfigError, match="SRAG_UNSLOTH_BASE_URL"):
        build_structured_model(settings(), provider="unsloth", model="m")
    build_structured_model(settings(), provider="ollama", model="m")  # no key, no error


def test_groq_names_its_missing_key() -> None:
    with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
        build_structured_model(settings(), provider="groq", model="m")


def test_the_structured_output_method_can_be_overridden() -> None:
    config = settings(unsloth_base_url="http://h/v1", llm_structured_method="function_calling")

    model = build_structured_model(config, provider="unsloth", model="m")

    assert model._method == "function_calling"  # type: ignore[attr-defined]


def test_groq_defaults_to_json_schema_but_can_be_overridden() -> None:
    default = build_structured_model(settings(groq_api_key="k"), provider="groq", model="m")
    forced = build_structured_model(
        settings(groq_api_key="k", llm_structured_method="function_calling"),
        provider="groq",
        model="m",
    )

    assert default._method == "json_schema"  # type: ignore[attr-defined]
    assert forced._method == "function_calling"  # type: ignore[attr-defined]


def test_the_requested_priority_order_is_the_default() -> None:
    assert DEFAULT_PRIORITY == (
        "openrouter",
        "groq",
        "nvidia",
        "unsloth",
        "google_genai",
        "ollama",
    )


def test_priority_text_is_parsed_in_order_and_validated() -> None:
    assert parse_priority("openrouter=a/b, groq=llama ,ollama=qwen") == [
        ("openrouter", "a/b"),
        ("groq", "llama"),
        ("ollama", "qwen"),
    ]
    for bad in ("", "groq", "groq=", "nope=m"):
        with pytest.raises(LLMConfigError):
            parse_priority(bad)


def test_the_chain_skips_unconfigured_providers_and_keeps_the_order() -> None:
    config = settings(groq_api_key="g", unsloth_base_url="http://h/v1")
    entries = parse_priority("openrouter=a,groq=b,nvidia=c,unsloth=d,ollama=e")

    chain = build_prioritized_model(config, entries)

    # openrouter and nvidia have no key: skipped; ollama needs none: kept, at the end
    assert chain.name == "chain:groq:b>unsloth:d>ollama:e"


def test_a_chain_with_nothing_usable_explains_why_without_secrets() -> None:
    entries = parse_priority("openrouter=a,groq=b")

    with pytest.raises(LLMConfigError, match=r"OPENROUTER_API_KEY.*GROQ_API_KEY"):
        build_prioritized_model(settings(), entries)


def test_a_single_usable_provider_is_not_wrapped() -> None:
    chain = build_prioritized_model(
        settings(groq_api_key="g"), parse_priority("openrouter=a,groq=b")
    )

    assert chain.name == "groq:b"


def test_the_large_tier_uses_the_priority_chain_when_set() -> None:
    config = settings(llm_priority="groq=x,ollama=y", groq_api_key="g")

    assert build_large_model(config).name == "chain:groq:x>ollama:y"
