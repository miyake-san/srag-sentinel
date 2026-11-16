from datetime import date

import pytest
from helpers import reader_connection, root_connection, writer_connection

from srag_sentinel.data.repository import (
    SurrealCountersReader,
    SurrealCountersWriter,
    WriteRejectedError,
)
from srag_sentinel.db.client import rows, run
from srag_sentinel.db.init import init_database
from srag_sentinel.domain.metrics import compute_metrics
from srag_sentinel.domain.models import DailyCounters
from srag_sentinel.settings import Settings

pytestmark = pytest.mark.integration


def counters(uf: str, day: date, **kw: int) -> DailyCounters:
    base = {
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
    base.update(kw)
    return DailyCounters(uf=uf, day=day, **base)


SAMPLE = [
    counters("SP", date(2026, 11, 14)),
    counters("SP", date(2026, 11, 15), cases=12),
    counters(
        "RJ",
        date(2026, 11, 15),
        cases=5,
        hosp_cases=4,
        outcome_known=3,
        deaths=1,
        uti_known=3,
        uti_yes=1,
        vac_cov_known=5,
        vac_cov_yes=2,
        vac_flu_known=5,
        vac_flu_yes=1,
    ),
]


async def test_upsert_is_idempotent_and_reader_sees_the_rows(settings: Settings) -> None:
    async with writer_connection(settings) as connection:
        writer = SurrealCountersWriter(connection)
        await writer.upsert_daily(SAMPLE)
        await writer.upsert_daily(SAMPLE)

    async with reader_connection(settings) as connection:
        reader = SurrealCountersReader(connection)
        month = (date(2026, 11, 1), date(2026, 11, 30))
        everything = await reader.daily_counters(uf="BR", start=month[0], end=month[1])
        only_sp = await reader.daily_counters(uf="SP", start=month[0], end=month[1])
        one_day = await reader.daily_counters(
            uf="BR", start=date(2026, 11, 15), end=date(2026, 11, 15)
        )
        latest = await reader.latest_day()

    def key(c: DailyCounters) -> tuple[date, str]:
        return (c.day, c.uf)

    assert sorted(everything, key=key) == sorted(SAMPLE, key=key)
    assert [c.uf for c in only_sp] == ["SP", "SP"]
    assert len(one_day) == 2
    assert latest == date(2026, 11, 15)


async def test_metrics_computed_from_database_match_in_memory_result(settings: Settings) -> None:
    async with writer_connection(settings) as connection:
        await SurrealCountersWriter(connection).upsert_daily(SAMPLE)

    async with reader_connection(settings) as connection:
        stored = await SurrealCountersReader(connection).daily_counters(
            uf="BR", start=date(2026, 10, 1), end=date(2026, 11, 30)
        )

    from_db = compute_metrics(stored, as_of=date(2026, 11, 15), window_days=30, scope="BR")
    in_memory = compute_metrics(SAMPLE, as_of=date(2026, 11, 15), window_days=30, scope="BR")
    assert from_db == in_memory
    assert from_db.cases_current == 27


async def test_latest_day_is_none_on_empty_database(settings: Settings) -> None:
    async with reader_connection(settings) as connection:
        assert await SurrealCountersReader(connection).latest_day() is None


async def test_read_only_user_cannot_change_data(settings: Settings) -> None:
    async with writer_connection(settings) as connection:
        await SurrealCountersWriter(connection).upsert_daily(SAMPLE)

    new_row = counters("MG", date(2026, 11, 15), cases=99)
    async with reader_connection(settings) as connection:
        # Denied writes do not raise: SurrealDB answers with an empty result.
        await run(connection, "DELETE srag_daily;")
        await run(connection, "UPDATE srag_daily SET cases = 999;")
        with pytest.raises(WriteRejectedError):
            await SurrealCountersWriter(connection).upsert_daily([new_row])

    async with root_connection(settings) as connection:
        final = await rows(connection, "SELECT uf, cases FROM srag_daily;")
    assert sorted((r["uf"], r["cases"]) for r in final) == [("RJ", 5), ("SP", 10), ("SP", 12)]


async def test_injection_shaped_uf_is_inert(settings: Settings) -> None:
    async with writer_connection(settings) as connection:
        await SurrealCountersWriter(connection).upsert_daily(SAMPLE)

    async with reader_connection(settings) as connection:
        found = await SurrealCountersReader(connection).daily_counters(
            uf="BR'; REMOVE TABLE srag_daily; --", start=date(2026, 11, 1), end=date(2026, 11, 30)
        )

    assert found == []
    async with root_connection(settings) as connection:
        assert len(await rows(connection, "SELECT uf FROM srag_daily;")) == 3


async def test_init_is_idempotent(settings: Settings) -> None:
    await init_database(settings)
    await init_database(settings)
