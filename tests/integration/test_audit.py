import asyncio

import pytest
from helpers import audit_reader_connection, audit_root_connection, audit_writer_connection
from surrealdb.errors import SurrealError

from srag_sentinel.db.client import rows, run
from srag_sentinel.governance.chain import verify_chain
from srag_sentinel.governance.model import AuditDraft
from srag_sentinel.governance.store import SurrealAuditStore
from srag_sentinel.settings import Settings

pytestmark = pytest.mark.integration


def draft(node: str, **details: str | int) -> AuditDraft:
    return AuditDraft(run_id="it-run", actor="agent", node=node, event="decision", details=details)


async def test_events_are_chained_persisted_and_verifiable(settings: Settings) -> None:
    async with audit_writer_connection(settings) as connection:
        store = SurrealAuditStore(connection)
        for index in range(3):
            await store.append(draft(f"n{index}", i=index))

    async with audit_reader_connection(settings) as connection:
        chain = await SurrealAuditStore(connection).read_all()

    assert [e.seq for e in chain] == [1, 2, 3]
    assert verify_chain(chain).ok
    assert chain[1].details == {"i": 1}


async def test_the_writer_cannot_update_or_delete_and_a_viewer_cannot_create(
    settings: Settings,
) -> None:
    async with audit_writer_connection(settings) as connection:
        await SurrealAuditStore(connection).append(draft("first"))
        # Denied writes return an empty result instead of raising.
        await run(connection, "UPDATE audit_event SET node = 'forged';")
        await run(connection, "DELETE audit_event;")

    async with audit_reader_connection(settings) as connection:
        await run(
            connection,
            "CREATE audit_event SET schema_version='x', seq=2, ts='t', run_id='r', actor='agent', "
            "node='intruder', event='decision', details={}, prev_hash='p', hash='h';",
        )

    async with audit_root_connection(settings) as connection:
        stored = await rows(connection, "SELECT node FROM audit_event;")
    assert [r["node"] for r in stored] == ["first"]


async def test_tampering_by_an_administrator_is_detected(settings: Settings) -> None:
    async with audit_writer_connection(settings) as connection:
        store = SurrealAuditStore(connection)
        for index in range(3):
            await store.append(draft(f"n{index}"))

    async with audit_root_connection(settings) as connection:
        await run(connection, "DELETE audit_event WHERE seq = 2;")  # admins can still delete

    async with audit_reader_connection(settings) as connection:
        result = verify_chain(await SurrealAuditStore(connection).read_all())
    assert (result.ok, result.failed_seq, result.reason) == (False, 3, "sequence gap")


async def test_readonly_fields_resist_even_administrators(settings: Settings) -> None:
    async with audit_writer_connection(settings) as connection:
        await SurrealAuditStore(connection).append(draft("original"))

    async with audit_root_connection(settings) as connection:
        with pytest.raises(SurrealError, match="readonly"):
            await run(connection, "UPDATE audit_event SET node = 'forged' WHERE seq = 1;")
        stored = await rows(connection, "SELECT node FROM audit_event;")
    assert [r["node"] for r in stored] == ["original"]


async def test_concurrent_writers_never_fork_the_chain(settings: Settings) -> None:
    async with (
        audit_writer_connection(settings) as first,
        audit_writer_connection(settings) as second,
    ):
        stores = [SurrealAuditStore(first), SurrealAuditStore(second)]
        await asyncio.gather(*(stores[i % 2].append(draft(f"c{i}")) for i in range(8)))

    async with audit_reader_connection(settings) as connection:
        chain = await SurrealAuditStore(connection).read_all()
    assert [e.seq for e in chain] == list(range(1, 9))
    assert verify_chain(chain).ok
