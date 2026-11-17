import pytest
from pydantic import BaseModel

from srag_sentinel.llm.fake import ScriptedModel
from srag_sentinel.llm.fallback import FallbackStructuredModel
from srag_sentinel.llm.ports import ModelError


class Answer(BaseModel):
    text: str


def scripted(name: str, *replies: object) -> ScriptedModel:
    return ScriptedModel(list(replies), model_name=name)  # type: ignore[arg-type]


async def test_the_first_provider_serves_when_it_works() -> None:
    first, second = scripted("a", Answer(text="one")), scripted("b", Answer(text="two"))
    chain = FallbackStructuredModel([first, second])

    result = await chain.invoke_structured(Answer, system="s", user="u")

    assert result.text == "one" and chain.served_by == "a"
    assert second.calls == []  # lower priorities are not even called


async def test_a_failing_provider_falls_through_to_the_next_in_order() -> None:
    chain = FallbackStructuredModel(
        [
            scripted("a", ModelError("rate limited")),
            scripted("b", ModelError("down")),
            scripted("c", Answer(text="three")),
            scripted("d", Answer(text="four")),
        ]
    )

    result = await chain.invoke_structured(Answer, system="s", user="u")

    assert result.text == "three" and chain.served_by == "c"


async def test_when_everything_fails_the_error_names_providers_not_content() -> None:
    chain = FallbackStructuredModel(
        [scripted("a", ModelError("secret detail")), scripted("b", ModelError("other"))]
    )

    with pytest.raises(ModelError) as caught:
        await chain.invoke_structured(Answer, system="s", user="u")

    assert "a, b" in str(caught.value) and "secret detail" not in str(caught.value)
    assert chain.served_by is None


def test_the_name_and_priority_show_the_order() -> None:
    chain = FallbackStructuredModel([scripted("x"), scripted("y")])

    assert chain.name == "chain:x>y" and chain.priority == ["x", "y"]


def test_an_empty_chain_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FallbackStructuredModel([])
