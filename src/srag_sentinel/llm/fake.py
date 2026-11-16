"""Deterministic scripted model for tests and offline runs."""

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from pydantic import BaseModel

from srag_sentinel.llm.ports import ModelError, T

Reply = BaseModel | Exception | Callable[[str, str], BaseModel]


@dataclass
class Call:
    """One recorded invocation."""

    schema: type[BaseModel]
    system: str
    user: str


@dataclass
class ScriptedModel:
    """Returns queued replies in order; an exception reply is raised; a callable is invoked.

    Records every call so tests can assert on prompts, schemas and call counts.
    """

    replies: Iterable[Reply]
    model_name: str = "fake:scripted"
    calls: list[Call] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._queue: deque[Reply] = deque(self.replies)

    @property
    def name(self) -> str:
        """Identifier recorded in audit events."""
        return self.model_name

    async def invoke_structured(self, schema: type[T], *, system: str, user: str) -> T:
        """Pop the next scripted reply (validated against ``schema``)."""
        self.calls.append(Call(schema, system, user))
        if not self._queue:
            raise ModelError(f"{self.model_name}: no scripted reply left")
        reply = self._queue.popleft()
        if isinstance(reply, Exception):
            raise reply
        output = reply(system, user) if callable(reply) else reply
        if not isinstance(output, schema):
            raise ModelError(f"{self.model_name}: scripted reply is not a {schema.__name__}")
        return output
