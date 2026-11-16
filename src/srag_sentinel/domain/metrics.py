"""Metric definitions M1-M4 (see docs/specs/02-data-and-metrics.md §6).

All functions are pure. Rates are ratios of sums, so aggregating daily counters first and
dividing afterwards is exact.
"""

from collections.abc import Iterable
from datetime import date

from srag_sentinel.domain.models import (
    CounterSet,
    DailyCounters,
    MetricResult,
    MetricsPayload,
)
from srag_sentinel.domain.windows import Window, window_pair

LOW_COMPLETENESS = 0.5
MATURITY_DAYS = 14

PROXY_ICU = (
    "Proxy: proporção de casos hospitalizados que usaram UTI; não mede a ocupação de leitos "
    "(o dataset não traz capacidade)."
)
PROXY_VACCINATION = "Proxy: vacinação entre os casos de SRAG, não cobertura vacinal da população."
LOW_OUTCOME = (
    "Desfecho conhecido em menos de 50% dos casos hospitalizados da janela; a taxa tende a "
    "estar subestimada e instável."
)
NO_PREVIOUS = "Sem casos na janela anterior: variação não calculável."
MATURITY = (
    "Dados dos últimos 14 dias ainda em consolidação (atraso de notificação): valores recentes "
    "tendem a ser revisados."
)


def ratio(numerator: int, denominator: int) -> float | None:
    """Return numerator/denominator, or None when the denominator is zero."""
    return numerator / denominator if denominator else None


def _within(counters: Iterable[DailyCounters], window: Window) -> CounterSet:
    return CounterSet.sum(c for c in counters if window.contains(c.day))


def _result(  # noqa: PLR0913 - a metric result carries many descriptive fields
    metric_id: str,
    label: str,
    numerator: int,
    denominator: int,
    window: Window,
    *,
    is_proxy: bool,
    base: int | None,
    caveats: tuple[str, ...] = (),
) -> MetricResult:
    """Build a result; ``base`` is the population the denominator should cover (completeness)."""
    completeness = ratio(denominator, base) if base is not None else None
    return MetricResult(
        metric_id=metric_id,
        label=label,
        value=ratio(numerator, denominator),
        numerator=numerator,
        denominator=denominator,
        window_start=window.start,
        window_end=window.end,
        is_proxy=is_proxy,
        completeness=completeness,
        caveats=caveats,
    )


def case_growth(current: CounterSet, previous: CounterSet, window: Window) -> MetricResult:
    """M1: relative change in notified cases versus the previous window."""
    caveats = () if previous.cases else (NO_PREVIOUS,)
    return _result(
        "M1",
        "Taxa de aumento de casos",
        current.cases - previous.cases,
        previous.cases,
        window,
        is_proxy=False,
        base=None,
        caveats=caveats,
    )


def mortality(totals: CounterSet, window: Window) -> MetricResult:
    """M2: deaths over hospitalized cases with a known outcome."""
    result = _result(
        "M2",
        "Taxa de mortalidade",
        totals.deaths,
        totals.outcome_known,
        window,
        is_proxy=False,
        base=totals.hosp_cases,
    )
    if result.completeness is not None and result.completeness < LOW_COMPLETENESS:
        return result.model_copy(update={"caveats": (LOW_OUTCOME,)})
    return result


def icu_usage(totals: CounterSet, window: Window) -> MetricResult:
    """M3 (proxy): hospitalized cases that used ICU over those with known ICU status."""
    return _result(
        "M3",
        "Proporção de internações em UTI (proxy da ocupação de UTI)",
        totals.uti_yes,
        totals.uti_known,
        window,
        is_proxy=True,
        base=totals.hosp_cases,
        caveats=(PROXY_ICU,),
    )


def vaccination_covid(totals: CounterSet, window: Window) -> MetricResult:
    """M4 (proxy): share of SRAG cases vaccinated against COVID-19."""
    return _result(
        "M4_COVID",
        "Vacinados contra COVID-19 entre casos de SRAG (proxy da taxa de vacinação)",
        totals.vac_cov_yes,
        totals.vac_cov_known,
        window,
        is_proxy=True,
        base=totals.cases,
        caveats=(PROXY_VACCINATION,),
    )


def vaccination_influenza(totals: CounterSet, window: Window) -> MetricResult:
    """M4 (proxy): share of SRAG cases vaccinated against influenza."""
    return _result(
        "M4_INFLUENZA",
        "Vacinados contra influenza entre casos de SRAG (proxy da taxa de vacinação)",
        totals.vac_flu_yes,
        totals.vac_flu_known,
        window,
        is_proxy=True,
        base=totals.cases,
        caveats=(PROXY_VACCINATION,),
    )


def compute_metrics(
    counters: Iterable[DailyCounters],
    *,
    as_of: date,
    window_days: int,
    scope: str,
    retrieved_on: date | None = None,
) -> MetricsPayload:
    """Compute all metrics for ``scope`` from daily counters (any UFs; they are summed)."""
    rows = list(counters)
    previous_window, current_window = window_pair(as_of, window_days)
    current = _within(rows, current_window)
    previous = _within(rows, previous_window)

    maturity: tuple[str, ...] = ()
    if retrieved_on is not None and (retrieved_on - as_of).days < MATURITY_DAYS:
        maturity = (MATURITY,)

    return MetricsPayload(
        scope=scope,
        as_of=as_of,
        window_days=window_days,
        current_window=current_window,
        previous_window=previous_window,
        cases_current=current.cases,
        cases_previous=previous.cases,
        metrics=(
            case_growth(current, previous, current_window),
            mortality(current, current_window),
            icu_usage(current, current_window),
            vaccination_covid(current, current_window),
            vaccination_influenza(current, current_window),
        ),
        data_maturity=maturity,
    )
