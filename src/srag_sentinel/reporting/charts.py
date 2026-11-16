"""SVG charts for the report (docs/specs/02 §7), drawn straight from the series payload.

matplotlib's object-oriented API is used on purpose: no ``pyplot`` global state, so rendering
is safe from several threads and leaves nothing open. The output is deterministic (fixed
hash salt, no embedded date) so a report can be reproduced byte by byte.
"""

import io
import re
from datetime import date
from typing import Any

import matplotlib as mpl
import numpy as np
from matplotlib.axes import Axes
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from srag_sentinel.domain.series import SeriesPayload

BAR = "#1f6f8b"
PARTIAL = "#9ec5d3"
LINE = "#c4472d"
INK = "#222222"
GRID = "#d9d9d9"

_PROLOG = re.compile(r"\A.*?(?=<svg\b)", re.DOTALL)
_SVG_TAG = re.compile(r"<svg\b([^>]*)>")
_RC: dict[Any, Any] = {
    "svg.fonttype": "none",
    "svg.hashsalt": "srag-sentinel",
    "font.family": "DejaVu Sans",
    "font.size": 9,
}


def _thousands(value: float, _position: int) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _finish(figure: Figure, *, key: str, title: str, description: str) -> str:
    """Serialise as inline-ready SVG with an accessible name and description."""
    buffer = io.BytesIO()
    with mpl.rc_context(_RC):
        figure.savefig(buffer, format="svg", metadata={"Date": None}, bbox_inches="tight")
    svg = _PROLOG.sub("", buffer.getvalue().decode("utf-8"))
    accessible = f'<title id="{key}-title">{_escape(title)}</title>'
    accessible += f'<desc id="{key}-desc">{_escape(description)}</desc>'

    def with_accessibility(match: re.Match[str]) -> str:
        attributes = (
            f' role="img" class="chart" aria-labelledby="{key}-title {key}-desc"{match.group(1)}'
        )
        return f"<svg{attributes}>{accessible}"

    return _SVG_TAG.sub(with_accessibility, svg, count=1)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _style(axes_title: str, axes: Axes) -> None:
    axes.set_title(axes_title, loc="left", fontsize=11, color=INK)
    axes.spines[["top", "right"]].set_visible(False)
    axes.grid(axis="y", color=GRID, linewidth=0.6)
    axes.set_axisbelow(True)
    axes.yaxis.set_major_formatter(FuncFormatter(_thousands))
    axes.set_ylabel("Casos notificados")


def _footer(figure: Figure, as_of: date) -> None:
    figure.text(
        0.0,
        -0.02,
        f"Fonte: OpenDATASUS (SRAG) · dados até {as_of:%d/%m/%Y}",
        fontsize=7.5,
        color="#555555",
    )


def daily_chart(series: SeriesPayload) -> str:
    """Cases per day for the last 30 days with the 7-day moving average."""
    figure = Figure(figsize=(7.2, 3.2), layout="constrained")
    axes = figure.subplots()
    days = np.array([point.day for point in series.daily], dtype="datetime64[D]")
    axes.bar(days, [p.cases for p in series.daily], color=BAR, width=0.8, label="Casos por dia")
    axes.plot(
        days,
        [p.moving_average_7d for p in series.daily],
        color=LINE,
        linewidth=1.8,
        label="Média móvel de 7 dias",
    )
    _style("Casos de SRAG por dia — últimos 30 dias", axes)
    axes.xaxis.set_major_formatter(DateFormatter("%d/%m"))  # type: ignore[no-untyped-call]
    axes.legend(frameon=False, loc="upper left")
    _footer(figure, series.as_of)
    first, last = series.daily[0].day, series.daily[-1].day
    total = sum(p.cases for p in series.daily)
    return _finish(
        figure,
        key="daily",
        title="Casos de SRAG por dia nos últimos 30 dias",
        description=(
            f"Barras diárias de {first:%d/%m/%Y} a {last:%d/%m/%Y}, somando {total} casos, "
            "com a média móvel de 7 dias."
        ),
    )


def monthly_chart(series: SeriesPayload) -> str:
    """Cases per month for the last 12 months; the current, incomplete month is hatched lighter."""
    figure = Figure(figsize=(7.2, 3.2), layout="constrained")
    axes = figure.subplots()
    months = [point.month for point in series.monthly]
    colors = [PARTIAL if point.is_partial else BAR for point in series.monthly]
    bars = axes.bar(months, [p.cases for p in series.monthly], color=colors)
    for bar, point in zip(bars, series.monthly, strict=True):
        if point.is_partial:
            bar.set_hatch("//")
            bar.set_edgecolor(BAR)
    _style("Casos de SRAG por mês — últimos 12 meses", axes)
    axes.tick_params(axis="x", rotation=45)
    if any(p.is_partial for p in series.monthly):
        axes.text(
            0.99,
            0.97,
            "Barra hachurada: mês em andamento (parcial)",
            transform=axes.transAxes,
            ha="right",
            va="top",
            fontsize=8,
            color="#555555",
        )
    _footer(figure, series.as_of)
    total = sum(p.cases for p in series.monthly)
    return _finish(
        figure,
        key="monthly",
        title="Casos de SRAG por mês nos últimos 12 meses",
        description=(
            f"Barras mensais de {series.monthly[0].month} a {series.monthly[-1].month}, "
            f"somando {total} casos; o mês corrente é parcial."
        ),
    )
