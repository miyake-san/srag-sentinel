"""The common result type of every guardrail (docs/specs/04 §2)."""

from dataclasses import dataclass, field
from typing import Literal

Action = Literal["allow", "sanitize", "block"]
Layer = Literal["G1", "G2", "G3", "G4"]


@dataclass(frozen=True)
class GuardrailVerdict:
    """One decision. Written to the audit trail and counted in OpenTelemetry by the caller.

    ``details`` must never contain request or model content, only field names, counts and codes.
    """

    layer: Layer
    rule_id: str
    action: Action
    details: dict[str, str | int | float | bool] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        """Whether this verdict stops the run."""
        return self.action == "block"
