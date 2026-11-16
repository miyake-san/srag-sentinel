"""Audit event models (schema ``audit.v1``)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "audit.v1"
GENESIS_HASH = "0" * 64

Actor = Literal["agent", "tool", "guardrail", "router", "system", "user"]
EventName = Literal[
    "run_start",
    "run_end",
    "llm_call",
    "tool_call",
    "guardrail_verdict",
    "decision",
    "degradation",
    "router_decision",
    "judge_verdict",
    "task_exhausted",
    "kg_write",
    "kg_quarantine",
]
Scalar = str | int | bool


class AuditDraft(BaseModel):
    """What a caller records. Content is represented by hashes and scalar details only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    actor: Actor
    node: str = Field(min_length=1)
    event: EventName
    inputs_hash: str | None = None
    outputs_hash: str | None = None
    details: dict[str, Scalar] = Field(default_factory=dict)

    @field_validator("details", mode="before")
    @classmethod
    def _no_floats(cls, value: dict[str, object]) -> dict[str, object]:
        """Floats can change representation through the database and would break the hash."""
        if any(isinstance(item, float) for item in value.values()):
            raise ValueError("details must not contain floats; use ints or strings")
        return value


class AuditEvent(BaseModel):
    """A sealed record in the chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    seq: int = Field(ge=1)
    ts: str
    run_id: str
    actor: Actor
    node: str
    event: EventName
    inputs_hash: str | None = None
    outputs_hash: str | None = None
    details: dict[str, Scalar] = Field(default_factory=dict)
    prev_hash: str
    hash: str
