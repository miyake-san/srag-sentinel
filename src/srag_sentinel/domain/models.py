"""Domain models: daily counters (the aggregates stored in the database) and metric results."""

from collections.abc import Iterable
from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from srag_sentinel.domain.windows import Window

COUNTER_FIELDS = (
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
)


class CounterSet(BaseModel):
    """Additive SRAG counters. Sums of valid counter sets are valid counter sets."""

    model_config = ConfigDict(frozen=True)

    cases: int = Field(ge=0, description="all valid notifications")
    hosp_cases: int = Field(ge=0, description="notifications with HOSPITAL = 1")
    outcome_known: int = Field(ge=0, description="hospitalized with EVOLUCAO in {1, 2, 3}")
    deaths: int = Field(ge=0, description="hospitalized with EVOLUCAO = 2")
    uti_known: int = Field(ge=0, description="hospitalized with UTI in {1, 2}")
    uti_yes: int = Field(ge=0, description="hospitalized with UTI = 1")
    vac_cov_known: int = Field(ge=0, description="cases with VACINA_COV in {1, 2}")
    vac_cov_yes: int = Field(ge=0, description="cases with VACINA_COV = 1")
    vac_flu_known: int = Field(ge=0, description="cases with VACINA in {1, 2}")
    vac_flu_yes: int = Field(ge=0, description="cases with VACINA = 1")

    @model_validator(mode="after")
    def _counters_are_consistent(self) -> Self:
        pairs = (
            ("hosp_cases", "cases"),
            ("outcome_known", "hosp_cases"),
            ("deaths", "outcome_known"),
            ("uti_known", "hosp_cases"),
            ("uti_yes", "uti_known"),
            ("vac_cov_known", "cases"),
            ("vac_cov_yes", "vac_cov_known"),
            ("vac_flu_known", "cases"),
            ("vac_flu_yes", "vac_flu_known"),
        )
        for part, whole in pairs:
            if getattr(self, part) > getattr(self, whole):
                raise ValueError(f"{part} cannot exceed {whole}")
        return self

    @classmethod
    def sum(cls, items: Iterable[CounterSet]) -> Self:
        """Add counter sets field by field (empty input gives all zeros)."""
        totals = dict.fromkeys(COUNTER_FIELDS, 0)
        for item in items:
            for name in COUNTER_FIELDS:
                totals[name] += getattr(item, name)
        return cls(**totals)


class DailyCounters(CounterSet):
    """Counters for one UF on one notification day."""

    uf: str
    day: date


class MetricResult(BaseModel):
    """One computed metric. ``value`` is ``None`` when it cannot be computed (never a silent 0)."""

    model_config = ConfigDict(frozen=True)

    metric_id: str
    label: str
    value: float | None
    numerator: int
    denominator: int
    window_start: date
    window_end: date
    is_proxy: bool
    completeness: float | None = None
    caveats: tuple[str, ...] = ()


class MetricsPayload(BaseModel):
    """Everything the report needs from the database: metrics plus window context."""

    model_config = ConfigDict(frozen=True)

    scope: str
    as_of: date
    window_days: int
    current_window: Window
    previous_window: Window
    cases_current: int
    cases_previous: int
    metrics: tuple[MetricResult, ...]
    data_maturity: tuple[str, ...] = ()
