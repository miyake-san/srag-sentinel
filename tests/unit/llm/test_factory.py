from typing import Any

import pytest
from pydantic import ValidationError

from srag_sentinel.llm import factory
from srag_sentinel.llm.factory import (
    PROVIDERS,
    LLMConfigError,
    build_large_model,
    build_structured_model,
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
