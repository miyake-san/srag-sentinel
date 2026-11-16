from datetime import date, timedelta

import pytest

from srag_sentinel.domain.series import daily_series, month_start, monthly_series

AS_OF = date(2026, 11, 15)


def test_daily_series_has_one_point_per_day_in_order_with_explicit_zeros() -> None:
    cases = {date(2026, 11, 15): 7, date(2026, 10, 17): 3}

    points = daily_series(cases, as_of=AS_OF, days=30)

    assert len(points) == 30
    assert points[0].day == date(2026, 10, 17)
    assert points[-1].day == AS_OF
    assert [p.day for p in points] == sorted(p.day for p in points)
    assert points[0].cases == 3
    assert points[-1].cases == 7
    assert points[5].cases == 0  # missing day is an explicit zero, not a gap


def test_daily_series_moving_average_is_trailing_seven_day_mean() -> None:
    cases = {AS_OF - timedelta(days=offset): 7 - offset for offset in range(7)}  # 7,6,5,...,1

    last = daily_series(cases, as_of=AS_OF, days=30)[-1]

    assert last.moving_average_7d == pytest.approx((7 + 6 + 5 + 4 + 3 + 2 + 1) / 7)


def test_daily_series_moving_average_uses_days_before_the_window() -> None:
    before_window = AS_OF - timedelta(days=30)  # one day before the 30-day window starts
    too_old = AS_OF - timedelta(days=36)  # outside the first point's trailing 7 days
    cases = {before_window: 70, too_old: 700}

    first = daily_series(cases, as_of=AS_OF, days=30)[0]  # window starts 29 days back

    assert first.cases == 0
    assert first.moving_average_7d == pytest.approx(10.0)  # 70 / 7; the 700 is too old


def test_monthly_series_covers_twelve_months_ending_in_the_as_of_month() -> None:
    cases = {
        date(2025, 12, 1): 5,
        date(2025, 12, 31): 6,
        date(2026, 11, 15): 4,
        date(2026, 1, 20): 9,
    }

    points = monthly_series(cases, as_of=AS_OF, months=12)

    assert points[0].month == "2025-12"
    assert points[-1].month == "2026-11"
    assert len(points) == 12
    by_month = {p.month: p for p in points}
    assert by_month["2025-12"].cases == 11
    assert by_month["2026-01"].cases == 9
    assert by_month["2026-02"].cases == 0
    assert by_month["2026-11"].cases == 4


def test_only_the_current_month_is_partial() -> None:
    points = monthly_series({}, as_of=AS_OF, months=12)

    assert [p.month for p in points if p.is_partial] == ["2026-11"]


def test_current_month_is_complete_on_its_last_day() -> None:
    points = monthly_series({}, as_of=date(2026, 11, 30), months=12)

    assert not any(p.is_partial for p in points)


def test_days_after_as_of_are_not_counted_in_the_monthly_total() -> None:
    cases = {date(2026, 11, 15): 4, date(2026, 11, 20): 100}

    assert monthly_series(cases, as_of=AS_OF, months=1)[0].cases == 4


def test_month_start_wraps_across_years() -> None:
    assert month_start(date(2026, 3, 9), back=2) == date(2026, 1, 1)
    assert month_start(date(2026, 1, 9), back=1) == date(2025, 12, 1)
    assert month_start(date(2026, 11, 15), back=11) == date(2025, 12, 1)
