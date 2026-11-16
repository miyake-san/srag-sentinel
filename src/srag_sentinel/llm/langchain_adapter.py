"""Adapter from a LangChain chat model to the :class:`StructuredModel` port."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from srag_sentinel.llm.ports import ModelError, T


class LangChainStructuredModel:
    """Runs a chat model with structured output (no tools are ever bound)."""

    def __init__(self, chat_model: BaseChatModel, *, name: str) -> None:
        self._chat_model = chat_model
        self._name = name

    @property
    def name(self) -> str:
        """Identifier recorded in audit events."""
        return self._name

    async def invoke_structured(self, schema: type[T], *, system: str, user: str) -> T:
        """Return a validated ``schema`` instance, or raise :class:`ModelError`."""
        runnable = self._chat_model.with_structured_output(schema)
        try:
            result = await runnable.ainvoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
        except Exception as error:
            raise ModelError(f"{self._name}: call failed ({type(error).__name__})") from error
        if isinstance(result, schema):
            return result
        try:
            return schema.model_validate(result)
        except ValueError as error:
            raise ModelError(f"{self._name}: output does not match {schema.__name__}") from error
