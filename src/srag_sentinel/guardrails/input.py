"""G1: validation of the report request at the system boundary."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError

from srag_sentinel.agent.tools.metrics import MIN_AS_OF, ScopeArgs
from srag_sentinel.guardrails.verdict import GuardrailVerdict

_FIELD_RULES = {
    "uf": "G1.uf",
    "as_of": "G1.as_of",
    "window_days": "G1.window_days",
    "settle_days": "G1.settle_days",
}


@dataclass(frozen=True)
class InputCheck:
    """Outcome of G1: a normalised request when allowed, plus every verdict."""

    request: ScopeArgs | None
    verdicts: tuple[GuardrailVerdict, ...]

    @property
    def blocked(self) -> bool:
        """Whether the request was rejected."""
        return any(verdict.blocked for verdict in self.verdicts)


def _block(rule_id: str, **details: str | int) -> GuardrailVerdict:
    return GuardrailVerdict("G1", rule_id, "block", dict(details))


def _verdicts_for(error: ValidationError) -> list[GuardrailVerdict]:
    verdicts = []
    for item in error.errors():
        location = str(item["loc"][0]) if item["loc"] else "body"
        if item["type"] == "extra_forbidden":
            verdicts.append(_block("G1.unknown_field", field=location))
        else:
            # Model-level validators have no field location; recognise the as_of range check.
            if location == "body" and "as_of" in str(item["msg"]):
                location = "as_of"
            rule = _FIELD_RULES.get(location, "G1.schema")
            verdicts.append(_block(rule, field=location, error=str(item["type"])))
    return verdicts


def check_request(raw: Mapping[str, Any], *, latest_day: date | None) -> InputCheck:
    """Validate a raw request; block unknown fields, bad values and dates after the data.

    Error details carry only the field name and error type, never the submitted value, so
    hostile input cannot leak into logs or audit records through this path.
    """
    try:
        request = ScopeArgs.model_validate(dict(raw))
    except ValidationError as error:
        return InputCheck(None, tuple(_verdicts_for(error)))

    if request.as_of is not None:
        if request.as_of < MIN_AS_OF:
            return InputCheck(None, (_block("G1.as_of", error="before_minimum"),))
        if latest_day is not None and request.as_of > latest_day:
            return InputCheck(None, (_block("G1.as_of", error="after_latest_data"),))
    return InputCheck(request, (GuardrailVerdict("G1", "G1.request", "allow"),))
