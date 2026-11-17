"""Process-level OpenTelemetry setup (OTLP over HTTP to the collector) and JSON logging."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from srag_sentinel import __version__
from srag_sentinel.observability.telemetry import SCOPE, Telemetry

SERVICE_NAME = "srag-sentinel"


@dataclass
class TelemetryRuntime:
    """The telemetry facade plus what must be flushed on shutdown."""

    telemetry: Telemetry
    providers: list[Any] = field(default_factory=list)

    def shutdown(self) -> None:
        """Flush and stop the providers."""
        for provider in self.providers:
            provider.shutdown()


def setup_telemetry(endpoint: str | None, *, environment: str = "dev") -> TelemetryRuntime:
    """Configure providers when an OTLP ``endpoint`` is given; otherwise stay a no-op."""
    if not endpoint:
        return TelemetryRuntime(Telemetry())
    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": __version__,
            "deployment.environment": environment,
        }
    )
    base = endpoint.rstrip("/")
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(f"{base}/v1/traces")))
    trace.set_tracer_provider(tracer_provider)
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(f"{base}/v1/metrics"))
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    telemetry = Telemetry(tracer_provider.get_tracer(SCOPE), meter_provider.get_meter(SCOPE))
    return TelemetryRuntime(telemetry, [tracer_provider, meter_provider])


class JsonFormatter(logging.Formatter):
    """One JSON object per line with the active ``trace_id`` and ``span_id``.

    Only the message and level are written: log call sites must never pass report content.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as JSON."""
        context = trace.get_current_span().get_span_context()
        body: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if context.is_valid:
            body["trace_id"] = format(context.trace_id, "032x")
            body["span_id"] = format(context.span_id, "016x")
        if record.exc_info:
            body["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else "Error"
        return json.dumps(body, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Send JSON logs to stderr (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    for noisy in ("fontTools", "weasyprint", "matplotlib", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.handlers = [handler]


def current_trace_id() -> str | None:
    """Hex trace id of the active span (for problem documents), if any."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
