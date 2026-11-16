"""Time series for the report charts (docs/specs/02 §7): daily 30 days and monthly 12 months."""

import calendar
from collections.abc import Mapping
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

MOVING_AVERAGE_DAYS = 7


class DailyPoint(BaseModel):
    """Cases notified on one day plus the trailing 7-day mean."""

    model_config = ConfigDict(frozen=True)

    day: date
    cases: int
    moving_average_7d: float


class MonthPoint(BaseModel):
    """Cases notified in one calendar month; the current month is marked as partial."""

    model_config = ConfigDict(frozen=True)

    month: str  # YYYY-MM
    cases: int
    is_partial: bool


class SeriesPayload(BaseModel):
    """Both chart series for a scope."""

    model_config = ConfigDict(frozen=True)

    scope: str
    as_of: date
    daily: tuple[DailyPoint, ...]
    monthly: tuple[MonthPoint, ...]


def month_start(reference: date, *, back: int) -> date:
    """First day of the month ``back`` months before the month of ``reference``."""
    index = reference.year * 12 + (reference.month - 1) - back
    return date(index // 12, index % 12 + 1, 1)


def daily_series(
    cases_by_day: Mapping[date, int], *, as_of: date, days: int = 30
) -> tuple[DailyPoint, ...]:
    """Cases per day for the ``days`` days ending at ``as_of``; missing days are explicit zeros.

    The moving average looks at the 6 days before each point too, so the first points of the
    window are not understated.
    """
    points = []
    for offset in range(days - 1, -1, -1):
        day = as_of - timedelta(days=offset)
        trailing = [
            cases_by_day.get(day - timedelta(days=lag), 0) for lag in range(MOVING_AVERAGE_DAYS)
        ]
        points.append(
            DailyPoint(
                day=day,
                cases=cases_by_day.get(day, 0),
                moving_average_7d=sum(trailing) / MOVING_AVERAGE_DAYS,
            )
        )
    return tuple(points)


def monthly_series(
    cases_by_day: Mapping[date, int], *, as_of: date, months: int = 12
) -> tuple[MonthPoint, ...]:
    """Cases per calendar month for the ``months`` months ending in the month of ``as_of``."""
    points = []
    for back in range(months - 1, -1, -1):
        start = month_start(as_of, back=back)
        last_day = calendar.monthrange(start.year, start.month)[1]
        end = date(start.year, start.month, last_day)
        total = sum(count for day, count in cases_by_day.items() if start <= day <= min(end, as_of))
        points.append(MonthPoint(month=f"{start:%Y-%m}", cases=total, is_partial=as_of < end))
    return tuple(points)
