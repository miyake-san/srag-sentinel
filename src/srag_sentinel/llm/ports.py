"""The only LLM interface the application depends on: structured output, no tools.

Keeping it this small decouples the router, judge and agent nodes from any one provider
SDK and makes them trivially testable with scripted fakes.
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ModelError(RuntimeError):
    """A model call failed or did not return output matching the requested schema."""


class StructuredModel(Protocol):
    """A model that answers a prompt with an instance of a Pydantic schema."""

    @property
    def name(self) -> str:
        """Identifier recorded in audit events, e.g. ``anthropic:claude-sonnet-5-5``."""
        ...

    async def invoke_structured(self, schema: type[T], *, system: str, user: str) -> T:
        """Return a validated ``schema`` instance, or raise :class:`ModelError`."""
        ...
