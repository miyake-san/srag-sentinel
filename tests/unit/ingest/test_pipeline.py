from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from srag_sentinel.data.ingest.pipeline import read_allowlisted, run_ingest, snapshot_sha256
from srag_sentinel.data.ingest.transform import ALLOWLIST, SchemaMismatchError
from srag_sentinel.domain.models import DailyCounters

TODAY = date(2026, 11, 16)


class FakeWriter:
    def __init__(self) -> None:
        self.rows: list[DailyCounters] = []
        self.manifests: list[dict[str, Any]] = []

    async def upsert_daily(self, rows: list[DailyCounters]) -> None:
        self.rows = rows

    async def record_manifest(self, manifest: dict[str, Any]) -> None:
        self.manifests.append(manifest)


def write_parquet(path: Path, days: list[datetime], *, extra_column: bool = False) -> str:
    frame = pl.DataFrame(
        {
            "DT_NOTIFIC": days,
            "SG_UF_NOT": ["SP"] * len(days),
            "HOSPITAL": ["1"] * len(days),
            "UTI": ["2"] * len(days),
            "EVOLUCAO": ["1"] * len(days),
            "VACINA_COV": ["1"] * len(days),
            "VACINA": ["2"] * len(days),
        }
    )
    if extra_column:
        frame = frame.with_columns(pl.lit("Maria Silva").alias("NM_PACIENTE"))
    frame.write_parquet(path)
    return str(path)


def test_read_allowlisted_never_materialises_other_columns(tmp_path: Path) -> None:
    source = write_parquet(tmp_path / "f.parquet", [datetime(2026, 11, 10)], extra_column=True)

    frame = read_allowlisted(source)

    assert frame.columns == list(ALLOWLIST)


def test_read_allowlisted_rejects_a_changed_layout(tmp_path: Path) -> None:
    path = tmp_path / "f.parquet"
    pl.DataFrame({"DT_NOTIFIC": [datetime(2026, 11, 10)]}).write_parquet(path)

    with pytest.raises(SchemaMismatchError, match="missing columns"):
        read_allowlisted(str(path))


async def test_files_for_different_years_are_merged_per_day(tmp_path: Path) -> None:
    year_2025 = write_parquet(tmp_path / "a.parquet", [datetime(2026, 11, 10)] * 2)
    year_2026 = write_parquet(
        tmp_path / "b.parquet", [datetime(2026, 11, 10), datetime(2026, 11, 11)]
    )
    writer = FakeWriter()

    manifest = await run_ingest(writer, [year_2025, year_2026], today=TODAY)

    by_day = {row.day: row.cases for row in writer.rows}
    assert by_day == {date(2026, 11, 10): 3, date(2026, 11, 11): 1}
    assert (manifest.rows_read, manifest.rows_kept) == (4, 4)
    assert manifest.source_urls == [year_2025, year_2026]
    assert writer.manifests[0]["snapshot_sha256"] == manifest.snapshot_sha256


async def test_same_input_gives_the_same_snapshot_hash(tmp_path: Path) -> None:
    source = write_parquet(tmp_path / "f.parquet", [datetime(2026, 11, 10)] * 3)

    first = await run_ingest(FakeWriter(), [source], today=TODAY)
    second = await run_ingest(FakeWriter(), [source], today=TODAY)

    assert first.snapshot_sha256 == second.snapshot_sha256


async def test_different_data_gives_a_different_snapshot_hash(tmp_path: Path) -> None:
    one = write_parquet(tmp_path / "a.parquet", [datetime(2026, 11, 10)])
    two = write_parquet(tmp_path / "b.parquet", [datetime(2026, 11, 10)] * 2)

    first = await run_ingest(FakeWriter(), [one], today=TODAY)
    second = await run_ingest(FakeWriter(), [two], today=TODAY)

    assert first.snapshot_sha256 != second.snapshot_sha256


def test_snapshot_hash_ignores_input_order() -> None:
    a = DailyCounters(
        uf="SP",
        day=date(2026, 11, 1),
        cases=1,
        hosp_cases=0,
        outcome_known=0,
        deaths=0,
        uti_known=0,
        uti_yes=0,
        vac_cov_known=0,
        vac_cov_yes=0,
        vac_flu_known=0,
        vac_flu_yes=0,
    )
    b = a.model_copy(update={"uf": "RJ"})

    assert snapshot_sha256([a, b]) == snapshot_sha256([b, a])
