"""Tools ``get_srag_metrics`` and ``get_srag_series`` (docs/specs/03 §3).

They accept a strict, validated argument model and only call fixed, parameterised repository
queries: no free-form SQL ever reaches the database.
"""

from datetime import date, timedelta
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from srag_sentinel.data.ingest.transform import UFS
from srag_sentinel.data.ports import CountersReader
from srag_sentinel.domain.metrics import compute_metrics
from srag_sentinel.domain.models import MetricsPayload
from srag_sentinel.domain.series import (
    MOVING_AVERAGE_DAYS,
    SeriesPayload,
    daily_series,
    month_start,
    monthly_series,
)

NATIONAL = "BR"
MIN_AS_OF = date(2019, 1, 1)
# The newest days are always incomplete (median notification lag is about 4 days, and weekends
# add dips), which would bias growth downwards. See ADR 0015.
DEFAULT_SETTLE_DAYS = 3
DAILY_POINTS = 30
MONTHLY_POINTS = 12


class NoDataError(RuntimeError):
    """The database has no aggregates to report on."""


class ScopeArgs(BaseModel):
    """Validated request scope shared by both tools."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uf: str = NATIONAL
    as_of: date | None = Field(
        default=None, description="defaults to the latest available day minus settle_days"
    )
    window_days: int = Field(default=30, ge=7, le=90)
    settle_days: int = Field(
        default=DEFAULT_SETTLE_DAYS,
        ge=0,
        le=14,
        description="most recent days left out when as_of is not given (notification lag)",
    )

    @field_validator("uf")
    @classmethod
    def _known_uf(cls, value: str) -> str:
        if value != NATIONAL and value not in UFS:
            raise ValueError("uf must be 'BR' or a valid UF code")
        return value

    @model_validator(mode="after")
    def _as_of_in_range(self) -> Self:
        if self.as_of is not None and self.as_of < MIN_AS_OF:
            raise ValueError(f"as_of must not be before {MIN_AS_OF}")
        return self


async def _resolve_as_of(reader: CountersReader, args: ScopeArgs) -> date:
    latest = await reader.latest_day()
    if latest is None:
        raise NoDataError("no data available; run `srag-sentinel ingest` first")
    if args.as_of is None:
        return max(latest - timedelta(days=args.settle_days), MIN_AS_OF)
    if args.as_of > latest:
        raise ValueError(f"as_of {args.as_of} is after the latest available day {latest}")
    return args.as_of


async def get_srag_metrics(reader: CountersReader, args: ScopeArgs) -> MetricsPayload:
    """Compute M1-M4 for ``args.uf`` over the window ending at ``as_of``."""
    as_of = await _resolve_as_of(reader, args)
    start = as_of - timedelta(days=2 * args.window_days - 1)
    counters = await reader.daily_counters(uf=args.uf, start=start, end=as_of)
    payload = compute_metrics(
        counters,
        as_of=as_of,
        window_days=args.window_days,
        scope=args.uf,
        retrieved_on=await reader.last_retrieved_on(),
    )
    latest = await reader.latest_day()
    if latest is not None and latest > as_of and args.as_of is None:
        note = (
            f"Os {(latest - as_of).days} dias mais recentes (após {as_of}) foram excluídos da "
            "análise por defasagem de notificação; eles ainda estão incompletos."
        )
        return payload.model_copy(update={"data_maturity": (note, *payload.data_maturity)})
    return payload


async def get_srag_series(reader: CountersReader, args: ScopeArgs) -> SeriesPayload:
    """Build the daily (30 days) and monthly (12 months) case series for ``args.uf``."""
    as_of = await _resolve_as_of(reader, args)
    start = min(
        month_start(as_of, back=MONTHLY_POINTS - 1),
        as_of - timedelta(days=DAILY_POINTS - 1 + MOVING_AVERAGE_DAYS - 1),
    )
    cases = await reader.daily_cases(uf=args.uf, start=start, end=as_of)
    return SeriesPayload(
        scope=args.uf,
        as_of=as_of,
        daily=daily_series(cases, as_of=as_of, days=DAILY_POINTS),
        monthly=monthly_series(cases, as_of=as_of, months=MONTHLY_POINTS),
    )
