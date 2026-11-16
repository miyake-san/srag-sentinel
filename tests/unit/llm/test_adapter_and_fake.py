from typing import Any

import pytest
from pydantic import BaseModel

from srag_sentinel.llm.fake import ScriptedModel
from srag_sentinel.llm.langchain_adapter import LangChainStructuredModel
from srag_sentinel.llm.ports import ModelError


class Answer(BaseModel):
    text: str


class Other(BaseModel):
    value: int


class StubRunnable:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.messages: list[Any] = []

    async def ainvoke(self, messages: list[Any]) -> Any:
        self.messages = messages
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class StubChatModel:
    def __init__(self, result: Any) -> None:
        self.runnable = StubRunnable(result)
        self.schema: type | None = None

    def with_structured_output(self, schema: type) -> StubRunnable:
        self.schema = schema
        return self.runnable


async def invoke(result: Any) -> Answer:
    model = LangChainStructuredModel(StubChatModel(result), name="stub:m")  # type: ignore[arg-type]
    return await model.invoke_structured(Answer, system="sys", user="usr")


async def test_adapter_returns_the_schema_instance_and_sends_both_messages() -> None:
    chat = StubChatModel(Answer(text="ok"))
    model = LangChainStructuredModel(chat, name="stub:m")  # type: ignore[arg-type]

    answer = await model.invoke_structured(Answer, system="sys", user="usr")

    assert answer == Answer(text="ok")
    assert chat.schema is Answer
    assert [type(m).__name__ for m in chat.runnable.messages] == ["SystemMessage", "HumanMessage"]
    assert model.name == "stub:m"


async def test_adapter_validates_dict_results() -> None:
    assert await invoke({"text": "from dict"}) == Answer(text="from dict")


async def test_adapter_rejects_output_that_does_not_match_the_schema() -> None:
    with pytest.raises(ModelError, match="does not match Answer"):
        await invoke({"wrong": 1})


async def test_adapter_wraps_provider_errors_without_leaking_their_message() -> None:
    with pytest.raises(ModelError) as info:
        await invoke(RuntimeError("secret-token-sk-123 rate limited"))

    assert "secret-token" not in str(info.value)
    assert "RuntimeError" in str(info.value)


async def test_scripted_model_replays_in_order_and_records_calls() -> None:
    model = ScriptedModel([Answer(text="one"), Answer(text="two")])

    first = await model.invoke_structured(Answer, system="s1", user="u1")
    second = await model.invoke_structured(Answer, system="s2", user="u2")

    assert (first.text, second.text) == ("one", "two")
    assert [(c.system, c.user) for c in model.calls] == [("s1", "u1"), ("s2", "u2")]


async def test_scripted_model_raises_scripted_errors_and_runs_callables() -> None:
    model = ScriptedModel([ModelError("boom"), lambda system, user: Answer(text=user.upper())])

    with pytest.raises(ModelError, match="boom"):
        await model.invoke_structured(Answer, system="s", user="u")
    assert (await model.invoke_structured(Answer, system="s", user="abc")).text == "ABC"


async def test_scripted_model_fails_when_exhausted_or_wrong_type() -> None:
    model = ScriptedModel([Other(value=1)])

    with pytest.raises(ModelError, match="not a Answer"):
        await model.invoke_structured(Answer, system="s", user="u")
    with pytest.raises(ModelError, match="no scripted reply"):
        await model.invoke_structured(Answer, system="s", user="u")
