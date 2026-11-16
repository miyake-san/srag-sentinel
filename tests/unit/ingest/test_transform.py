"""Hand-computed expectations; see the row-by-row comments in ``FRAME``."""

from datetime import date, datetime

import polars as pl
import pytest

from srag_sentinel.data.ingest.transform import (
    ALLOWLIST,
    SchemaMismatchError,
    aggregate,
    clean,
    merge,
    to_counters,
    validate_schema,
)
from srag_sentinel.domain.models import DailyCounters

TODAY = date(2026, 11, 16)
SCHEMA = {
    "DT_NOTIFIC": pl.Datetime("ns"),
    "SG_UF_NOT": pl.Utf8,
    "HOSPITAL": pl.Utf8,
    "UTI": pl.Utf8,
    "EVOLUCAO": pl.Utf8,
    "VACINA_COV": pl.Utf8,
    "VACINA": pl.Utf8,
}


def frame(rows: list[tuple[object, ...]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHEMA, orient="row")


FRAME = frame(
    [
        # 1: SP hospitalized, ICU, died, vaccinated covid, not flu
        (datetime(2026, 11, 10), "SP", "1", "1", "2", "1", "2"),
        # 2: SP hospitalized, no ICU, cured, not covid, flu vaccinated
        (datetime(2026, 11, 10), "SP", "1", "2", "1", "2", "1"),
        # 3: SP not hospitalized (counts as a case only); vaccination ignored/missing
        (datetime(2026, 11, 10), "SP", "2", "1", "2", "9", None),
        # 4: lower-case UF; missing HOSPITAL; invalid UTI code; vaccinated for both
        (datetime(2026, 11, 11), "rj", None, "7", "3", "1", "1"),
        # 5: no notification date -> dropped
        (None, "SP", "1", "1", "1", "1", "1"),
        # 6: future date -> dropped
        (datetime(2027, 1, 1), "SP", "1", "1", "1", "1", "1"),
        # 7: unknown UF; hospitalized, ICU no, outcome ignored, vaccination "no" for both
        (datetime(2026, 11, 11), None, "1", "2", "9", "2", "2"),
    ]
)


@pytest.fixture
def aggregated() -> pl.DataFrame:
    cleaned, _ = clean(FRAME, today=TODAY)
    return aggregate(cleaned)


def counters_for(aggregated: pl.DataFrame, uf: str, day: date) -> DailyCounters:
    return next(c for c in to_counters(aggregated) if c.uf == uf and c.day == day)


def test_drop_stats_count_removed_and_normalised_rows() -> None:
    _, stats = clean(FRAME, today=TODAY)

    assert (stats.rows_read, stats.rows_kept) == (7, 5)
    assert stats.dropped == {
        "missing_notification_date": 1,
        "notification_date_out_of_range": 1,
        "unknown_uf_mapped": 1,
        "hospital_mapped_to_ignored": 1,
        "uti_mapped_to_ignored": 1,
        "evolucao_mapped_to_ignored": 0,
        "vacina_cov_mapped_to_ignored": 0,
        "vacina_mapped_to_ignored": 1,
    }


def test_sp_counters_for_the_day(aggregated: pl.DataFrame) -> None:
    sp = counters_for(aggregated, "SP", date(2026, 11, 10))

    assert sp.cases == 3
    assert sp.hosp_cases == 2
    assert (sp.outcome_known, sp.deaths) == (2, 1)
    assert (sp.uti_known, sp.uti_yes) == (2, 1)
    assert (sp.vac_cov_known, sp.vac_cov_yes) == (2, 1)
    assert (sp.vac_flu_known, sp.vac_flu_yes) == (2, 1)


def test_non_hospitalized_and_normalised_rows(aggregated: pl.DataFrame) -> None:
    rj = counters_for(aggregated, "RJ", date(2026, 11, 11))

    assert rj.cases == 1
    assert rj.hosp_cases == 0  # missing HOSPITAL is "ignored", not hospitalized
    assert (rj.outcome_known, rj.deaths, rj.uti_known, rj.uti_yes) == (0, 0, 0, 0)
    assert (rj.vac_cov_known, rj.vac_cov_yes, rj.vac_flu_known, rj.vac_flu_yes) == (1, 1, 1, 1)


def test_unknown_uf_goes_to_xx_and_ignored_outcome_is_not_known(aggregated: pl.DataFrame) -> None:
    xx = counters_for(aggregated, "XX", date(2026, 11, 11))

    assert (xx.cases, xx.hosp_cases) == (1, 1)
    assert (xx.outcome_known, xx.deaths) == (0, 0)
    assert (xx.uti_known, xx.uti_yes) == (1, 0)
    assert (xx.vac_cov_known, xx.vac_cov_yes) == (1, 0)


def test_total_cases_equal_kept_rows(aggregated: pl.DataFrame) -> None:
    assert sum(c.cases for c in to_counters(aggregated)) == 5


def test_merge_sums_the_same_day_coming_from_two_files() -> None:
    cleaned, _ = clean(FRAME, today=TODAY)
    once = aggregate(cleaned)

    merged = to_counters(merge([once, once]))

    assert sum(c.cases for c in merged) == 10
    assert len(merged) == once.height


def test_merge_of_nothing_is_empty() -> None:
    assert to_counters(merge([])) == []


def test_clean_keeps_only_allowlisted_columns() -> None:
    wide = FRAME.with_columns(pl.lit("secret").alias("NM_PACIENTE"))

    cleaned, _ = clean(wide, today=TODAY)

    assert "NM_PACIENTE" not in cleaned.columns


def test_validate_schema_accepts_expected_columns() -> None:
    validate_schema(FRAME.schema)


def test_validate_schema_reports_missing_columns() -> None:
    with pytest.raises(SchemaMismatchError, match="UTI"):
        validate_schema(FRAME.drop("UTI").schema)


def test_validate_schema_requires_a_temporal_notification_date() -> None:
    text_dates = FRAME.with_columns(pl.col("DT_NOTIFIC").cast(pl.Utf8))

    with pytest.raises(SchemaMismatchError, match="DT_NOTIFIC"):
        validate_schema(text_dates.schema)


def test_allowlist_has_no_identifying_columns() -> None:
    forbidden = {"NU_NOTIFIC", "CS_SEXO", "DT_NASC", "NU_IDADE_N", "ID_MUNICIP", "CO_MUN_NOT"}

    assert not forbidden & set(ALLOWLIST)
