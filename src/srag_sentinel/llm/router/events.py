"""Router events. Sinks forward them to the audit trail and OpenTelemetry (later tasks)."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

EventKind = Literal[
    "router_decision",
    "validation",
    "judge_verdict",
    "task_accepted",
    "task_exhausted",
]
Detail = str | int | float | bool


@dataclass(frozen=True)
class RouterEvent:
    """One decision or outcome; ``details`` never carries model input/output text."""

    kind: EventKind
    task: str
    tier: str | None = None
    attempt: int | None = None
    details: dict[str, Detail] = field(default_factory=dict)


class EventSink(Protocol):
    """Receives router events."""

    def emit(self, event: RouterEvent) -> None:
        """Record ``event``."""
        ...


class NullSink:
    """Discards events."""

    def emit(self, event: RouterEvent) -> None:
        """Ignore ``event``."""


class ListSink:
    """Collects events in memory (tests and diagnostics)."""

    def __init__(self) -> None:
        self.events: list[RouterEvent] = []

    def emit(self, event: RouterEvent) -> None:
        """Store ``event``."""
        self.events.append(event)

    def kinds(self) -> list[str]:
        """Return the kinds of all collected events, in order."""
        return [event.kind for event in self.events]
