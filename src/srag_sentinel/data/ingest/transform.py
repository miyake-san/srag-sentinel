"""Cleaning and aggregation: allowlisted patient-level columns -> daily per-UF counters.

Only the columns in :data:`ALLOWLIST` are ever read. Individual rows never leave this module:
the output is one counter row per (UF, notification day).
"""

from datetime import date

import polars as pl
from pydantic import BaseModel, ConfigDict

from srag_sentinel.domain.models import COUNTER_FIELDS, DailyCounters

ALLOWLIST = ("DT_NOTIFIC", "SG_UF_NOT", "HOSPITAL", "UTI", "EVOLUCAO", "VACINA_COV", "VACINA")

UFS = frozenset(
    [
        "AC",
        "AL",
        "AP",
        "AM",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MT",
        "MS",
        "MG",
        "PA",
        "PB",
        "PR",
        "PE",
        "PI",
        "RJ",
        "RN",
        "RS",
        "RO",
        "RR",
        "SC",
        "SP",
        "SE",
        "TO",
    ]
)
UNKNOWN_UF = "XX"
MIN_DAY = date(2019, 1, 1)

_YES_NO_IGNORED = ("1", "2", "9")
_OUTCOMES = ("1", "2", "3", "9")
_CATEGORICAL_DOMAINS = {
    "HOSPITAL": _YES_NO_IGNORED,
    "UTI": _YES_NO_IGNORED,
    "EVOLUCAO": _OUTCOMES,
    "VACINA_COV": _YES_NO_IGNORED,
    "VACINA": _YES_NO_IGNORED,
}


class SchemaMismatchError(ValueError):
    """The source file does not have the columns/types the ingestion expects."""


class DropStats(BaseModel):
    """Counts of rows dropped or normalised, recorded in the ingestion manifest."""

    model_config = ConfigDict(frozen=True)

    rows_read: int
    rows_kept: int
    dropped: dict[str, int]


def validate_schema(schema: pl.Schema) -> None:
    """Fail loudly if the allowlisted columns are missing or the date column is not temporal."""
    missing = [name for name in ALLOWLIST if name not in schema.names()]
    if missing:
        raise SchemaMismatchError(f"missing columns: {', '.join(missing)}")
    if not schema["DT_NOTIFIC"].is_temporal():
        raise SchemaMismatchError(f"DT_NOTIFIC must be a date/datetime, got {schema['DT_NOTIFIC']}")


def clean(frame: pl.DataFrame, *, today: date) -> tuple[pl.DataFrame, DropStats]:
    """Normalise codes and drop rows without a usable notification date."""
    dropped: dict[str, int] = {}
    work = frame.select(ALLOWLIST).with_columns(pl.col("DT_NOTIFIC").cast(pl.Date).alias("day"))

    missing_date = int(work["day"].null_count())
    in_range = (pl.col("day") >= MIN_DAY) & (pl.col("day") <= today)
    out_of_range = int(work.filter(pl.col("day").is_not_null() & ~in_range).height)
    work = work.filter(in_range)
    dropped["missing_notification_date"] = missing_date
    dropped["notification_date_out_of_range"] = out_of_range

    uf = pl.col("SG_UF_NOT").cast(pl.Utf8).str.strip_chars().str.to_uppercase()
    unknown_uf = int(work.select((~uf.is_in(list(UFS))).fill_null(value=True).sum()).item())
    dropped["unknown_uf_mapped"] = unknown_uf
    work = work.with_columns(
        pl.when(uf.is_in(list(UFS))).then(uf).otherwise(pl.lit(UNKNOWN_UF)).alias("uf")
    )

    for column, domain in _CATEGORICAL_DOMAINS.items():
        value = pl.col(column).cast(pl.Utf8).str.strip_chars()
        invalid = int(work.select((~value.is_in(list(domain))).fill_null(value=True).sum()).item())
        dropped[f"{column.lower()}_mapped_to_ignored"] = invalid
        work = work.with_columns(
            pl.when(value.is_in(list(domain))).then(value).otherwise(pl.lit("9")).alias(column)
        )

    stats = DropStats(rows_read=frame.height, rows_kept=work.height, dropped=dropped)
    return work.select("uf", "day", *_CATEGORICAL_DOMAINS), stats


def aggregate(clean_frame: pl.DataFrame) -> pl.DataFrame:
    """Aggregate cleaned rows into counters per (uf, day) following docs/specs/02 §2.1."""
    hosp = pl.col("HOSPITAL") == "1"
    uti_known = hosp & pl.col("UTI").is_in(["1", "2"])
    outcome_known = hosp & pl.col("EVOLUCAO").is_in(["1", "2", "3"])
    counters = clean_frame.group_by("uf", "day").agg(
        pl.len().alias("cases"),
        hosp.sum().alias("hosp_cases"),
        outcome_known.sum().alias("outcome_known"),
        (hosp & (pl.col("EVOLUCAO") == "2")).sum().alias("deaths"),
        uti_known.sum().alias("uti_known"),
        (hosp & (pl.col("UTI") == "1")).sum().alias("uti_yes"),
        pl.col("VACINA_COV").is_in(["1", "2"]).sum().alias("vac_cov_known"),
        (pl.col("VACINA_COV") == "1").sum().alias("vac_cov_yes"),
        pl.col("VACINA").is_in(["1", "2"]).sum().alias("vac_flu_known"),
        (pl.col("VACINA") == "1").sum().alias("vac_flu_yes"),
    )
    return counters.with_columns(pl.col(*COUNTER_FIELDS).cast(pl.Int64)).sort("uf", "day")


def merge(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Sum aggregates from several files (one day can appear in more than one yearly file)."""
    if not frames:
        return pl.DataFrame(
            schema={"uf": pl.Utf8, "day": pl.Date, **dict.fromkeys(COUNTER_FIELDS, pl.Int64)}
        )
    return pl.concat(frames).group_by("uf", "day").sum().sort("uf", "day")


def to_counters(aggregated: pl.DataFrame) -> list[DailyCounters]:
    """Convert an aggregate frame to validated domain objects."""
    return [DailyCounters(**row) for row in aggregated.iter_rows(named=True)]
