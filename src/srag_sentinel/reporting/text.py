"""Plain-text rendering of metrics and series for the command line."""

from srag_sentinel.domain.models import MetricResult, MetricsPayload
from srag_sentinel.domain.series import SeriesPayload

PROXY_TAG = " [proxy]"


def _percent(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "n/d"
    return f"{value * 100:+.1f}%" if signed else f"{value * 100:.1f}%"


def _metric_lines(metric: MetricResult) -> list[str]:
    signed = metric.metric_id == "M1"
    head = f"{metric.label}{PROXY_TAG if metric.is_proxy else ''}"
    value = _percent(metric.value, signed=signed)
    detail = f"  valor: {value}  ({metric.numerator}/{metric.denominator})"
    if metric.completeness is not None:
        detail += f"  completude: {_percent(metric.completeness)}"
    return [head, detail, *(f"  ! {caveat}" for caveat in metric.caveats)]


def format_metrics(payload: MetricsPayload) -> str:
    """Render the four metrics with their numerators, denominators and caveats."""
    window = payload.current_window
    lines = [
        f"SRAG — escopo {payload.scope} — dados até {payload.as_of}",
        f"Janela atual: {window.start} a {window.end} ({payload.window_days} dias)",
        f"Casos: {payload.cases_current} (anterior: {payload.cases_previous})",
        "",
    ]
    for metric in payload.metrics:
        lines.extend(_metric_lines(metric))
    lines.extend(f"! {warning}" for warning in payload.data_maturity)
    return "\n".join(lines)


def format_series(series: SeriesPayload) -> str:
    """Render the daily (30 days) and monthly (12 months) series."""
    lines = ["", "Casos por dia (últimos 30 dias)  [média móvel 7d]"]
    lines.extend(f"  {p.day}  {p.cases:>6}  {p.moving_average_7d:>8.1f}" for p in series.daily)
    lines.extend(["", "Casos por mês (últimos 12 meses)"])
    lines.extend(
        f"  {p.month}  {p.cases:>7}{'  (parcial)' if p.is_partial else ''}" for p in series.monthly
    )
    return "\n".join(lines)
