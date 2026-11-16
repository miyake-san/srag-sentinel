from datetime import date

import pytest
from pydantic import ValidationError

from srag_sentinel.domain.models import CounterSet, DailyCounters


def make_daily(**overrides: int) -> DailyCounters:
    values = {
        "cases": 10,
        "hosp_cases": 8,
        "outcome_known": 6,
        "deaths": 2,
        "uti_known": 7,
        "uti_yes": 3,
        "vac_cov_known": 9,
        "vac_cov_yes": 4,
        "vac_flu_known": 9,
        "vac_flu_yes": 2,
    }
    values.update(overrides)
    return DailyCounters(uf="SP", day=date(2026, 11, 1), **values)


def test_valid_counters_are_accepted_and_immutable() -> None:
    counters = make_daily()

    with pytest.raises(ValidationError):
        counters.cases = 99  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"hosp_cases": 11},  # more hospitalized than cases
        {"outcome_known": 9},  # more known outcomes than hospitalized
        {"deaths": 7},  # more deaths than known outcomes
        {"uti_known": 9},  # more ICU-known than hospitalized
        {"uti_yes": 8},  # more ICU-yes than ICU-known
        {"vac_cov_known": 11},  # more known vaccination than cases
        {"vac_cov_yes": 10},  # more vaccinated than known
        {"vac_flu_known": 11},
        {"vac_flu_yes": 10},
        {"cases": -1},
    ],
)
def test_inconsistent_counters_are_rejected(overrides: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        make_daily(**overrides)


def test_sum_adds_every_counter() -> None:
    total = CounterSet.sum([make_daily(), make_daily()])

    assert total.cases == 20
    assert total.deaths == 4
    assert total.vac_flu_yes == 4


def test_sum_of_nothing_is_all_zeros() -> None:
    total = CounterSet.sum([])

    assert total.cases == 0
    assert total.hosp_cases == 0
