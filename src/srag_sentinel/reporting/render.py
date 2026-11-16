"""HTML and JSON renderers. The HTML is self-contained: inline CSS and SVG, no script, no remote."""

import hashlib
from collections.abc import Mapping
from datetime import date, datetime
from functools import lru_cache
from importlib import resources
from urllib.parse import urlsplit

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from markupsafe import Markup

from srag_sentinel.agent.report import ReportDraft
from srag_sentinel.reporting.charts import daily_chart, monthly_chart
from srag_sentinel.reporting.models import ArtifactHashes, ReportDocument

DEGRADATION_TEXT: Mapping[str, str] = {
    "NEWS_UNAVAILABLE": "Notícias indisponíveis: o contexto externo não foi incluído.",
    "PLAN_FALLBACK": "A busca de notícias usou consultas padrão em vez das propostas pelo modelo.",
    "NARRATIVE_REJECTED": (
        "A narrativa gerada não passou na verificação e foi omitida; "
        "apenas métricas e gráficos são apresentados."
    ),
    "PDF_UNAVAILABLE": "O PDF não pôde ser gerado; HTML e JSON estão disponíveis.",
}
ALLOWED_SCHEMES = frozenset({"http", "https"})
CONTENT_SECURITY_POLICY = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"


def sha256_hex(content: bytes) -> str:
    """Hex SHA-256 of a rendered artifact."""
    return hashlib.sha256(content).hexdigest()


def percent(value: float | None, *, signed: bool = False) -> str:
    """Brazilian-format percentage (``12,3%``); ``n/d`` when the metric could not be computed."""
    if value is None:
        return "n/d"
    text = f"{value * 100:+.1f}" if signed else f"{value * 100:.1f}"
    return text.replace(".", ",") + "%"


def integer(value: int) -> str:
    """Integer with Brazilian thousands separators."""
    return f"{value:,}".replace(",", ".")


def date_br(value: date | datetime | None) -> str:
    """``dd/mm/aaaa`` (or ``n/d``)."""
    return "n/d" if value is None else f"{value:%d/%m/%Y}"


def safe_url(url: str) -> str:
    """Return the URL only when it is plain http(s); anything else renders as an empty link."""
    parts = urlsplit(url)
    return url if parts.scheme.lower() in ALLOWED_SCHEMES and parts.netloc else ""


@lru_cache(maxsize=1)
def _environment() -> Environment:
    environment = Environment(
        loader=PackageLoader("srag_sentinel.reporting", "templates"),
        autoescape=select_autoescape(default=True, default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters.update(
        pct=percent, pct_signed=lambda v: percent(v, signed=True), num=integer, date_br=date_br
    )
    environment.filters["safe_url"] = safe_url
    return environment


@lru_cache(maxsize=1)
def _stylesheet() -> str:
    return (
        resources.files("srag_sentinel.reporting")
        .joinpath("templates/report.css")
        .read_text("utf-8")
    )


def render_html(draft: ReportDraft) -> str:
    """Render the report as one self-contained HTML document.

    Model and news text is data: the environment escapes it, and nothing from them is ever
    marked safe. Only the chart SVGs (generated here from numbers) and our own stylesheet are.
    """
    template = _environment().get_template("report.html.j2")
    return template.render(
        report=draft,
        css=Markup(_stylesheet()),  # noqa: S704 - our own static stylesheet
        csp=CONTENT_SECURITY_POLICY,
        daily_svg=Markup(daily_chart(draft.series)),  # noqa: S704 - built from numbers only
        monthly_svg=Markup(monthly_chart(draft.series)),  # noqa: S704 - built from numbers only
        degradation_text=DEGRADATION_TEXT,
        articles={article.ref: article for article in draft.articles},
        metric_labels={metric.metric_id: metric.label for metric in draft.metrics.metrics},
    )


def render_json(draft: ReportDraft, *, html: str, pdf: bytes | None) -> str:
    """Serialise ``report.json`` with the hashes of the HTML (and PDF, when produced)."""
    document = ReportDocument(
        report=draft,
        artifacts=ArtifactHashes(
            html_sha256=sha256_hex(html.encode("utf-8")),
            pdf_sha256=sha256_hex(pdf) if pdf is not None else None,
        ),
    )
    return document.model_dump_json(indent=2)
