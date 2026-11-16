from datetime import date

import pytest
from pydantic import ValidationError

from srag_sentinel.agent.tools.metrics import (
    NoDataError,
    ScopeArgs,
    get_srag_metrics,
    get_srag_series,
)
from srag_sentinel.domain.models import DailyCounters

LATEST = date(2026, 11, 15)


def make(uf: str, day: date, cases: int) -> DailyCounters:
    return DailyCounters(
        uf=uf,
        day=day,
        cases=cases,
        hosp_cases=cases,
        outcome_known=cases,
        deaths=cases // 10,
        uti_known=cases,
        uti_yes=cases // 5,
        vac_cov_known=cases,
        vac_cov_yes=cases // 2,
        vac_flu_known=cases,
        vac_flu_yes=cases // 4,
    )


class FakeReader:
    def __init__(self, rows: list[DailyCounters], retrieved_on: date | None = None) -> None:
        self._rows = rows
        self._retrieved_on = retrieved_on

    async def daily_counters(self, *, uf: str, start: date, end: date) -> list[DailyCounters]:
        return [r for r in self._rows if start <= r.day <= end and uf in ("BR", r.uf)]

    async def daily_cases(self, *, uf: str, start: date, end: date) -> dict[date, int]:
        totals: dict[date, int] = {}
        for row in await self.daily_counters(uf=uf, start=start, end=end):
            totals[row.day] = totals.get(row.day, 0) + row.cases
        return totals

    async def latest_day(self) -> date | None:
        return max((r.day for r in self._rows), default=None)

    async def last_retrieved_on(self) -> date | None:
        return self._retrieved_on


ROWS = [
    make("SP", date(2026, 9, 20), 100),  # previous window
    make("SP", date(2026, 11, 15), 120),  # current window
    make("RJ", date(2026, 11, 15), 30),
    make("RJ", date(2026, 11, 1), 50),
]


async def test_metrics_default_to_the_latest_day_and_national_scope() -> None:
    payload = await get_srag_metrics(FakeReader(ROWS), ScopeArgs())

    assert payload.as_of == LATEST
    assert payload.scope == "BR"
    assert payload.cases_current == 200  # 120 + 30 + 50
    assert payload.cases_previous == 100


async def test_metrics_can_be_scoped_to_one_uf() -> None:
    payload = await get_srag_metrics(FakeReader(ROWS), ScopeArgs(uf="RJ"))

    assert payload.cases_current == 80


async def test_explicit_as_of_is_honoured() -> None:
    payload = await get_srag_metrics(FakeReader(ROWS), ScopeArgs(as_of=date(2026, 11, 1)))

    assert payload.as_of == date(2026, 11, 1)
    assert payload.cases_current == 50


async def test_as_of_after_the_latest_available_day_is_rejected() -> None:
    with pytest.raises(ValueError, match="after the latest"):
        await get_srag_metrics(FakeReader(ROWS), ScopeArgs(as_of=date(2026, 12, 1)))


async def test_empty_database_is_reported_clearly() -> None:
    with pytest.raises(NoDataError, match="ingest"):
        await get_srag_metrics(FakeReader([]), ScopeArgs())
    with pytest.raises(NoDataError):
        await get_srag_series(FakeReader([]), ScopeArgs())


async def test_recent_ingestion_adds_a_maturity_warning() -> None:
    fresh = await get_srag_metrics(FakeReader(ROWS, retrieved_on=date(2026, 11, 16)), ScopeArgs())
    old = await get_srag_metrics(FakeReader(ROWS, retrieved_on=date(2026, 12, 31)), ScopeArgs())

    assert fresh.data_maturity
    assert not old.data_maturity


async def test_series_have_thirty_daily_and_twelve_monthly_points() -> None:
    series = await get_srag_series(FakeReader(ROWS), ScopeArgs())

    assert len(series.daily) == 30
    assert len(series.monthly) == 12
    assert series.daily[-1].cases == 150  # 120 + 30 on the last day
    november = series.monthly[-1]
    assert (november.month, november.cases, november.is_partial) == ("2026-11", 200, True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"uf": "XX"},
        {"uf": "sp"},
        {"uf": "BR'; REMOVE"},
        {"window_days": 6},
        {"window_days": 91},
        {"as_of": date(2018, 12, 31)},
        {"unexpected": 1},
    ],
)
def test_invalid_arguments_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ScopeArgs(**kwargs)  # type: ignore[arg-type]


def test_valid_arguments_are_accepted() -> None:
    args = ScopeArgs(uf="SP", as_of=date(2026, 1, 1), window_days=90)

    assert (args.uf, args.window_days) == ("SP", 90)
