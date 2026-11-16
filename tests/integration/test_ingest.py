from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest
from helpers import reader_connection, root_connection

from srag_sentinel.data.ingest.service import ingest
from srag_sentinel.data.repository import SurrealCountersReader
from srag_sentinel.db.client import rows
from srag_sentinel.settings import Settings

pytestmark = pytest.mark.integration


def write_fixture(path: Path) -> str:
    pl.DataFrame(
        {
            "DT_NOTIFIC": [datetime(2026, 11, 10), datetime(2026, 11, 10), datetime(2026, 11, 11)],
            "SG_UF_NOT": ["SP", "SP", "RJ"],
            "HOSPITAL": ["1", "1", "1"],
            "UTI": ["1", "2", "2"],
            "EVOLUCAO": ["2", "1", "1"],
            "VACINA_COV": ["1", "2", "1"],
            "VACINA": ["2", "2", "1"],
            "NM_PACIENTE": ["a", "b", "c"],
        }
    ).write_parquet(path)
    return str(path)


async def test_ingest_loads_aggregates_and_manifest_and_is_idempotent(
    settings: Settings, tmp_path: Path
) -> None:
    source = write_fixture(tmp_path / "srag.parquet")

    first = await ingest(settings, [source])
    second = await ingest(settings, [source])

    async with reader_connection(settings) as connection:
        stored = await SurrealCountersReader(connection).daily_counters(
            uf="BR", start=date(2026, 11, 1), end=date(2026, 11, 30)
        )
    sp = next(c for c in stored if c.uf == "SP")
    assert (sp.cases, sp.deaths, sp.uti_yes) == (2, 1, 1)
    assert sum(c.cases for c in stored) == 3  # rerun did not double the counts
    assert first.snapshot_sha256 == second.snapshot_sha256

    async with root_connection(settings) as connection:
        manifests = await rows(
            connection, "SELECT snapshot_sha256, rows_kept FROM ingest_manifest;"
        )
        every_field = await rows(connection, "SELECT * FROM srag_daily;")
    assert len(manifests) == 2
    assert {m["snapshot_sha256"] for m in manifests} == {first.snapshot_sha256}
    assert all("NM_PACIENTE" not in row for row in every_field)
