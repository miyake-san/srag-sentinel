"""Priority failover across providers: try each model in order, serve from the first that answers.

This is separate from the task router (small -> large, ADR 0018): the router chooses *which tier*
runs a task, this chooses *which provider* serves a tier. A provider that is down, rate-limited or
returns an unusable answer is skipped; only when every provider fails does the call fail.
"""

from collections.abc import Sequence

from srag_sentinel.llm.ports import ModelError, StructuredModel, T


class FallbackStructuredModel:
    """A :class:`StructuredModel` that fails over through ``models`` in priority order."""

    def __init__(self, models: Sequence[StructuredModel]) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self._models = list(models)
        self.served_by: str | None = None

    @property
    def name(self) -> str:
        """``chain:first>second>...`` (the audit trail also gets the model that served the call)."""
        return "chain:" + ">".join(model.name for model in self._models)

    @property
    def priority(self) -> list[str]:
        """Names of the providers in the order they are tried."""
        return [model.name for model in self._models]

    async def invoke_structured(self, schema: type[T], *, system: str, user: str) -> T:
        """Return the first successful answer; raise :class:`ModelError` if all providers fail."""
        failed: list[str] = []
        for model in self._models:
            try:
                result = await model.invoke_structured(schema, system=system, user=user)
            except ModelError:
                failed.append(model.name)
                continue
            self.served_by = model.name
            return result
        self.served_by = None
        raise ModelError(f"all providers failed: {', '.join(failed)}")
