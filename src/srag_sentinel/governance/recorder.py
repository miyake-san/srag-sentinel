"""Per-run recorder: queue events synchronously, write them to the chain on ``flush``."""

from collections.abc import Iterable, Mapping
from typing import Any

from srag_sentinel.governance.chain import content_hash
from srag_sentinel.governance.model import Actor, AuditDraft, AuditEvent, EventName, Scalar
from srag_sentinel.governance.store import AuditStore
from srag_sentinel.guardrails.verdict import GuardrailVerdict
from srag_sentinel.llm.router.events import RouterEvent

_ROUTER_EVENTS: Mapping[str, EventName] = {
    "router_decision": "router_decision",
    "judge_verdict": "judge_verdict",
    "task_exhausted": "task_exhausted",
}


def _scalars(details: Mapping[str, Any]) -> dict[str, Scalar]:
    """Keep audit details scalar and float-free (floats are rendered as text)."""
    clean: dict[str, Scalar] = {}
    for key, value in details.items():
        clean[key] = str(value) if isinstance(value, float) else value
    return clean


class AuditRecorder:
    """Collects events for one run. Content is never stored, only hashes and scalars."""

    def __init__(self, run_id: str, store: AuditStore) -> None:
        self._run_id = run_id
        self._store = store
        self._pending: list[AuditDraft] = []

    def record(  # noqa: PLR0913 - an audit record has several independent attributes
        self,
        *,
        actor: Actor,
        node: str,
        event: EventName,
        inputs: Any = None,
        outputs: Any = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue one event; ``inputs``/``outputs`` are hashed, never stored."""
        self._pending.append(
            AuditDraft(
                run_id=self._run_id,
                actor=actor,
                node=node,
                event=event,
                inputs_hash=None if inputs is None else content_hash(inputs),
                outputs_hash=None if outputs is None else content_hash(outputs),
                details=_scalars(details or {}),
            )
        )

    def record_verdicts(self, verdicts: Iterable[GuardrailVerdict]) -> None:
        """Queue one ``guardrail_verdict`` event per verdict."""
        for verdict in verdicts:
            self.record(
                actor="guardrail",
                node=verdict.layer,
                event="guardrail_verdict",
                details={"rule_id": verdict.rule_id, "action": verdict.action, **verdict.details},
            )

    def router_sink(self) -> RouterAuditSink:
        """Return an :class:`EventSink` that feeds router events into this recorder."""
        return RouterAuditSink(self)

    async def flush(self) -> list[AuditEvent]:
        """Write all queued events in order; any failure propagates and aborts the run."""
        written: list[AuditEvent] = []
        while self._pending:
            draft = self._pending[0]
            written.append(await self._store.append(draft))
            self._pending.pop(0)
        return written


class RouterAuditSink:
    """Adapts router events (sync ``emit``) to audit records."""

    def __init__(self, recorder: AuditRecorder) -> None:
        self._recorder = recorder

    def emit(self, event: RouterEvent) -> None:
        """Queue ``event`` (validation and acceptance are recorded as plain decisions)."""
        details: dict[str, Any] = {"kind": event.kind, **event.details}
        if event.tier is not None:
            details["tier"] = event.tier
        if event.attempt is not None:
            details["attempt"] = event.attempt
        self._recorder.record(
            actor="router",
            node=event.task,
            event=_ROUTER_EVENTS.get(event.kind, "decision"),
            details=details,
        )
