"""The :class:`Telemetry` facade: spans, metrics and the bridge from audit events.

Every attribute is a scalar taken from the audit event's ``details`` (counts, ids, codes), which
by design never hold prompts, articles or personal data. With no SDK configured the OpenTelemetry
API is a no-op, so the facade costs nothing in tests and local runs.
"""

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Span, Status, StatusCode, Tracer

SCOPE = "srag_sentinel"
_ALLOWED = (str, int, bool)


def _attrs(details: Mapping[str, Any], *keys: str) -> dict[str, str | int | bool]:
    """Pick scalar attributes by key (anything non-scalar is dropped, never stringified)."""
    return {k: details[k] for k in keys if k in details and isinstance(details[k], _ALLOWED)}


class Telemetry:
    """Creates spans and records the ``srag.*`` metrics."""

    def __init__(self, tracer: Tracer | None = None, meter: Meter | None = None) -> None:
        self._tracer = tracer or trace.get_tracer(SCOPE)
        meter = meter or metrics.get_meter(SCOPE)
        self._reports = meter.create_counter("srag.report.total", description="reports by status")
        self._report_seconds = meter.create_histogram("srag.report.duration", unit="s")
        self._node_seconds = meter.create_histogram("srag.node.duration", unit="s")
        self._guardrails = meter.create_counter("srag.guardrail.verdicts")
        self._router_calls = meter.create_counter("srag.router.calls")
        self._escalations = meter.create_counter("srag.router.escalations")
        self._judge = meter.create_counter("srag.judge.verdicts")
        self._tools = meter.create_counter("srag.tool.calls")
        self._kg_written = meter.create_counter("srag.kg.nodes_written")
        self._kg_quarantined = meter.create_counter("srag.kg.quarantined")
        self._kg_items = meter.create_histogram("srag.kg.retrieval.items")
        self._degradations = meter.create_counter("srag.report.degradations")
        self._api_rejections = meter.create_counter("srag.api.rejections")

    # -- spans -----------------------------------------------------------------------------

    @contextmanager
    def span(self, name: str, **attributes: str | int | bool) -> Iterator[Span]:
        """A span that records an exception and marks itself failed before re-raising."""
        with self._tracer.start_as_current_span(name, attributes=attributes) as span:
            try:
                yield span
            except Exception as error:
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                span.record_exception(error)
                raise

    @contextmanager
    def node(self, name: str) -> Iterator[None]:
        """Span and duration for one graph node."""
        started = time.monotonic()
        with self.span("agent.node", **{"srag.node": name}):
            try:
                yield
            finally:
                self._node_seconds.record(time.monotonic() - started, {"node": name})

    def report_finished(self, status: str, seconds: float, degradations: tuple[str, ...]) -> None:
        """Count a finished report and its degradations."""
        self._reports.add(1, {"status": status})
        self._report_seconds.record(seconds, {"status": status})
        for code in degradations:
            self._degradations.add(1, {"code": code})

    def api_rejected(self, reason: str) -> None:
        """Count a request refused at the API perimeter (reason is a fixed code, never a key)."""
        self._api_rejections.add(1, {"reason": reason})

    # -- audit bridge ----------------------------------------------------------------------

    def on_event(self, actor: str, node: str, event: str, details: Mapping[str, Any]) -> None:
        """Mirror one audit event into the current span and the metrics."""
        current = trace.get_current_span()
        if current.is_recording():
            current.add_event(
                event,
                {
                    "srag.node": node,
                    "srag.actor": actor,
                    **_attrs(details, "kind", "tier", "rule_id", "action", "status"),
                },
            )
        if event in {"router_decision", "judge_verdict", "task_exhausted"}:
            self._count_router(event, node, details)
        else:
            self._count_other(event, node, details)

    def _count_router(self, event: str, node: str, details: Mapping[str, Any]) -> None:
        if event == "router_decision":
            self._router_calls.add(
                1, {"task": node, "tier": str(details.get("tier", "")), "outcome": "attempt"}
            )
            if details.get("reason") == "escalation":
                self._escalations.add(1, {"task": node})
        elif event == "judge_verdict":
            self._judge.add(
                1, {"rubric": str(details.get("rubric", "")), "passed": bool(details.get("passed"))}
            )
        else:
            self._router_calls.add(1, {"task": node, "tier": "", "outcome": "exhausted"})

    def _count_other(self, event: str, node: str, details: Mapping[str, Any]) -> None:
        if event == "guardrail_verdict":
            self._guardrails.add(1, {"layer": node, **_attrs(details, "rule_id", "action")})
        elif event == "tool_call":
            self._tools.add(1, {"tool": node})
            if node == "search_knowledge_graph" and isinstance(details.get("items"), int):
                self._kg_items.record(details["items"])
        elif event == "kg_write":
            self._kg_written.add(1, {"kind": str(details.get("kind", ""))})
        elif event == "kg_quarantine":
            self._kg_quarantined.add(1, {"reason": str(details.get("kind", ""))})
