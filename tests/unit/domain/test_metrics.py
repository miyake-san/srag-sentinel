"""Metric tests: expected values are computed by hand from the fixture in the comments below.

as_of = 2026-11-15, window = 30 days
  current  window: 2026-10-17 .. 2026-11-15
  previous window: 2026-09-17 .. 2026-10-16

Totals (hand-added):
  previous: cases 150
  current : cases 210, hosp 190, outcome_known 60, deaths 5,
            uti_known 170, uti_yes 44, vac_cov 70/180, vac_flu 37/160
"""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from srag_sentinel.domain.metrics import compute_metrics, ratio
from srag_sentinel.domain.models import DailyCounters, MetricResult, MetricsPayload

AS_OF = date(2026, 11, 15)


def row(uf: str, day: date, **kw: int) -> DailyCounters:
    zero = dict.fromkeys(
        (
            "cases",
            "hosp_cases",
            "outcome_known",
            "deaths",
            "uti_known",
            "uti_yes",
            "vac_cov_known",
            "vac_cov_yes",
            "vac_flu_known",
            "vac_flu_yes",
        ),
        0,
    )
    zero.update(kw)
    return DailyCounters(uf=uf, day=day, **zero)


FIXTURE = [
    # previous window
    row(
        "SP",
        date(2026, 9, 20),
        cases=100,
        hosp_cases=90,
        outcome_known=60,
        deaths=6,
        uti_known=80,
        uti_yes=20,
        vac_cov_known=90,
        vac_cov_yes=45,
        vac_flu_known=80,
        vac_flu_yes=20,
    ),
    row(
        "RJ",
        date(2026, 10, 10),
        cases=50,
        hosp_cases=40,
        outcome_known=30,
        deaths=4,
        uti_known=35,
        uti_yes=7,
        vac_cov_known=45,
        vac_cov_yes=9,
        vac_flu_known=40,
        vac_flu_yes=4,
    ),
    # current window
    row(
        "SP",
        date(2026, 10, 17),
        cases=120,
        hosp_cases=110,
        outcome_known=40,
        deaths=4,
        uti_known=100,
        uti_yes=30,
        vac_cov_known=100,
        vac_cov_yes=50,
        vac_flu_known=90,
        vac_flu_yes=30,
    ),
    row(
        "RJ",
        date(2026, 11, 15),
        cases=90,
        hosp_cases=80,
        outcome_known=20,
        deaths=1,
        uti_known=70,
        uti_yes=14,
        vac_cov_known=80,
        vac_cov_yes=20,
        vac_flu_known=70,
        vac_flu_yes=7,
    ),
    # outside both windows (must be ignored)
    row("SP", date(2026, 9, 16), cases=1000, hosp_cases=1000),
    row("SP", date(2026, 11, 16), cases=1000, hosp_cases=1000),
]


@pytest.fixture
def payload() -> MetricsPayload:
    return compute_metrics(FIXTURE, as_of=AS_OF, window_days=30, scope="BR")


def metric(payload: MetricsPayload, metric_id: str) -> MetricResult:
    return next(m for m in payload.metrics if m.metric_id == metric_id)


def test_m1_case_growth_is_relative_change_between_windows(payload: MetricsPayload) -> None:
    m1 = metric(payload, "M1")

    assert m1.value == pytest.approx(0.4)  # (210 - 150) / 150
    assert (m1.numerator, m1.denominator) == (60, 150)
    assert (m1.window_start, m1.window_end) == (date(2026, 10, 17), AS_OF)
    assert not m1.is_proxy


def test_m2_mortality_uses_known_outcomes_among_hospitalized(payload: MetricsPayload) -> None:
    m2 = metric(payload, "M2")

    assert m2.value == pytest.approx(5 / 60)
    assert (m2.numerator, m2.denominator) == (5, 60)
    assert m2.completeness == pytest.approx(60 / 190)
    assert any("desfecho" in c.lower() for c in m2.caveats)  # completeness < 50 %


def test_m3_icu_is_flagged_as_proxy(payload: MetricsPayload) -> None:
    m3 = metric(payload, "M3")

    assert m3.value == pytest.approx(44 / 170)
    assert (m3.numerator, m3.denominator) == (44, 170)
    assert m3.is_proxy
    assert any("leitos" in c for c in m3.caveats)


def test_m4_vaccination_covid_and_influenza_are_proxies(payload: MetricsPayload) -> None:
    covid = metric(payload, "M4_COVID")
    flu = metric(payload, "M4_INFLUENZA")

    assert covid.value == pytest.approx(70 / 180)
    assert flu.value == pytest.approx(37 / 160)
    assert covid.is_proxy
    assert flu.is_proxy
    assert covid.completeness == pytest.approx(180 / 210)


def test_payload_exposes_window_totals_and_scope(payload: MetricsPayload) -> None:
    assert payload.scope == "BR"
    assert payload.cases_current == 210
    assert payload.cases_previous == 150
    assert payload.as_of == AS_OF


def test_empty_previous_window_gives_no_growth_instead_of_zero() -> None:
    only_current = [FIXTURE[2], FIXTURE[3]]

    m1 = metric(compute_metrics(only_current, as_of=AS_OF, window_days=30, scope="BR"), "M1")

    assert m1.value is None
    assert any("anterior" in c for c in m1.caveats)


def test_empty_data_yields_none_values_never_zero() -> None:
    payload = compute_metrics([], as_of=AS_OF, window_days=30, scope="BR")

    assert all(m.value is None for m in payload.metrics)
    assert all(m.completeness is None for m in payload.metrics if m.metric_id != "M1")


def test_recent_extraction_adds_a_data_maturity_warning() -> None:
    fresh = compute_metrics(
        FIXTURE, as_of=AS_OF, window_days=30, scope="BR", retrieved_on=date(2026, 11, 16)
    )
    settled = compute_metrics(
        FIXTURE, as_of=AS_OF, window_days=30, scope="BR", retrieved_on=date(2026, 12, 15)
    )

    assert fresh.data_maturity
    assert not settled.data_maturity


def test_ratio_handles_zero_denominator() -> None:
    assert ratio(1, 0) is None
    assert ratio(0, 5) == 0.0
    assert ratio(1, 4) == 0.25


@given(
    cases=st.lists(st.integers(min_value=0, max_value=500), min_size=1, max_size=20),
    data=st.data(),
)
def test_rates_stay_between_zero_and_one(cases: list[int], data: st.DataObject) -> None:
    rows = []
    for index, total in enumerate(cases):
        hosp = data.draw(st.integers(min_value=0, max_value=total))
        known = data.draw(st.integers(min_value=0, max_value=hosp))
        deaths = data.draw(st.integers(min_value=0, max_value=known))
        uti_known = data.draw(st.integers(min_value=0, max_value=hosp))
        uti_yes = data.draw(st.integers(min_value=0, max_value=uti_known))
        vac_known = data.draw(st.integers(min_value=0, max_value=total))
        vac_yes = data.draw(st.integers(min_value=0, max_value=vac_known))
        rows.append(
            row(
                "SP",
                date(2026, 11, 1 + index),
                cases=total,
                hosp_cases=hosp,
                outcome_known=known,
                deaths=deaths,
                uti_known=uti_known,
                uti_yes=uti_yes,
                vac_cov_known=vac_known,
                vac_cov_yes=vac_yes,
                vac_flu_known=vac_known,
                vac_flu_yes=vac_yes,
            )
        )

    result = compute_metrics(rows, as_of=date(2026, 11, 30), window_days=30, scope="BR")

    for m in result.metrics:
        if m.metric_id != "M1" and m.value is not None:
            assert 0.0 <= m.value <= 1.0
