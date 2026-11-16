"""Judge port and verdict model (the LLM-backed judge and rubrics arrive in T6c)."""

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from srag_sentinel.llm.router.validators import Issue


class Verdict(BaseModel):
    """Structured judgement of a candidate output against a rubric."""

    model_config = ConfigDict(frozen=True)

    score: int = Field(ge=1, le=5)
    passed: bool
    reasons: list[str] = Field(default_factory=list, max_length=3)
    issues: list[str] = Field(default_factory=list, description="codes from a closed list")


class Judge(Protocol):
    """Evaluates a candidate output; never sees tools and treats ``source`` as data."""

    async def evaluate(
        self,
        *,
        rubric: str,
        source: str,
        output: BaseModel,
        issues: Sequence[Issue],
    ) -> Verdict:
        """Return a verdict for ``output`` given the original ``source`` text."""
        ...
