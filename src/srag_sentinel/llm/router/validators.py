"""Deterministic validators run before (and independently of) any LLM judge.

An ``error`` issue is a hard failure the judge can never override. A ``warning`` marks an
ambiguous case the judge may decide.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Issue:
    """A problem found in a candidate output."""

    code: str
    message: str
    severity: Severity = "error"


Validator = Callable[[BaseModel, Any], Sequence[Issue]]
"""``validator(output, payload) -> issues``; ``payload`` is the task input."""


def schema_ok(output: BaseModel, payload: Any) -> Sequence[Issue]:
    """Marker validator: the structured-output schema is already enforced by the model port."""
    return ()


def max_items(field_name: str, limit: int) -> Validator:
    """Build a validator that caps the length of a list field."""

    def check(output: BaseModel, payload: Any) -> Sequence[Issue]:
        items = getattr(output, field_name)
        if len(items) > limit:
            return (Issue("too_many_items", f"{field_name} has {len(items)} items; max {limit}"),)
        return ()

    return check


BUILTIN_VALIDATORS: Mapping[str, Validator] = {"schema": schema_ok}
