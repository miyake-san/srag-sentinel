"""Spans and metrics of a full graph run, read from in-memory exporters (no DB, no network)."""

import json
import logging

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from test_graph import build

from srag_sentinel.agent.graph import run_report
from srag_sentinel.observability.setup import JsonFormatter, setup_telemetry
from srag_sentinel.observability.telemetry import Telemetry

NODES = {
    "validate_request",
    "fetch_metrics",
    "plan_news",
    "collect_news",
    "build_kg",
    "retrieve_context",
    "synthesize",
    "verify_narrative",
    "render_report",
    "finalize",
}


def instrumented() -> tuple[Telemetry, InMemorySpanExporter, InMemoryMetricReader]:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    telemetry = Telemetry(tracer_provider.get_tracer("t"), meter_provider.get_meter("t"))
    return telemetry, exporter, reader


def metric_points(reader: InMemoryMetricReader) -> dict[str, list[dict[str, object]]]:
    found: dict[str, list[dict[str, object]]] = {}
    data = reader.get_metrics_data()
    for resource in data.resource_metrics if data else []:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                found[metric.name] = [dict(p.attributes) for p in metric.data.data_points]
    return found


async def test_a_run_emits_one_span_per_node_and_the_srag_metrics() -> None:
    telemetry, exporter, reader = instrumented()
    deps, _, _, _ = build()
    deps.telemetry = telemetry
    deps.recorder._telemetry = telemetry  # the service wires this; the test builds deps by hand

    await run_report(deps, {"uf": "BR", "settle_days": 0})

    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert names.count("report.run") == 1
    assert {s.attributes["srag.node"] for s in spans if s.name == "agent.node"} == NODES
    run = next(s for s in spans if s.name == "report.run")
    assert all(s.parent is not None for s in spans if s.name == "agent.node")
    assert run.parent is None

    points = metric_points(reader)
    assert {"status": "ok"} in points["srag.report.total"]
    assert {"node": "synthesize"} in points["srag.node.duration"]
    assert any(p["tier"] == "small" for p in points["srag.router.calls"])
    assert "srag.guardrail.verdicts" in points


async def test_no_span_or_metric_attribute_carries_report_content() -> None:
    telemetry, exporter, reader = instrumented()
    deps, _, _, _ = build()
    deps.telemetry = telemetry
    deps.recorder._telemetry = telemetry

    await run_report(deps, {"uf": "BR", "settle_days": 0})

    values: list[str] = []
    for span in exporter.get_finished_spans():
        values += [str(v) for v in span.attributes.values()]
        for event in span.events:
            values += [str(v) for v in event.attributes.values()]
    for attributes in metric_points(reader).values():
        values += [str(v) for point in attributes for v in point.values()]
    blob = " ".join(values)
    for secret in ("InfoGripe", "Casos recuaram", "Fiocruz", "síndrome respiratória"):
        assert secret not in blob


async def test_a_failing_node_marks_its_span_as_an_error() -> None:
    telemetry, exporter, _ = instrumented()

    try:
        with telemetry.node("boom"):
            raise RuntimeError("x")
    except RuntimeError:
        pass

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code.name == "ERROR"


def test_without_an_endpoint_setup_is_a_noop() -> None:
    runtime = setup_telemetry(None)

    runtime.shutdown()
    assert isinstance(runtime.telemetry, Telemetry)


def test_json_logs_are_one_object_per_line_and_carry_the_trace_id() -> None:
    telemetry, _, _ = instrumented()
    record = logging.LogRecord("srag", logging.INFO, __file__, 1, "run %s done", ("r1",), None)

    with telemetry.span("s"):
        line = JsonFormatter().format(record)

    body = json.loads(line)
    assert body["message"] == "run r1 done" and len(body["trace_id"]) == 32
