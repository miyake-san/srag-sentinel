"""Audit stores: an in-memory chain (tests, offline) and the SurrealDB ``audit`` database.

The SurrealDB store signs in as the record-access user ``audit_writer``: it can create and read
events but not update or delete them (ADR 0013). A denied write returns an empty result
instead of raising, so every write is checked and a failure aborts the run.
"""

import asyncio
from typing import Any, Protocol

from surrealdb import AsyncSurrealConnection
from surrealdb.errors import ValidationError

from srag_sentinel.db.client import rows
from srag_sentinel.governance.chain import seal
from srag_sentinel.governance.model import GENESIS_HASH, AuditDraft, AuditEvent

_COLUMNS = (
    "schema_version, seq, ts, run_id, actor, node, event, "
    "inputs_hash, outputs_hash, details, prev_hash, hash"
)
_MAX_ATTEMPTS = 5


class AuditWriteError(RuntimeError):
    """An audit record could not be written; the run must not continue without its trail."""


class AuditStore(Protocol):
    """Appends sealed events to the chain and reads them back."""

    async def append(self, draft: AuditDraft) -> AuditEvent:
        """Seal ``draft`` onto the chain and persist it."""
        ...

    async def read_all(self) -> list[AuditEvent]:
        """Return every event ordered by ``seq``."""
        ...


class MemoryAuditStore:
    """Chain kept in memory; shares the sealing logic with the real store."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self._lock = asyncio.Lock()

    async def append(self, draft: AuditDraft) -> AuditEvent:
        """Seal ``draft`` onto the chain."""
        async with self._lock:
            head = self.events[-1] if self.events else None
            event = seal(
                draft,
                seq=head.seq + 1 if head else 1,
                prev_hash=head.hash if head else GENESIS_HASH,
            )
            self.events.append(event)
            return event

    async def read_all(self) -> list[AuditEvent]:
        """Return every event ordered by ``seq``."""
        return list(self.events)


class SurrealAuditStore:
    """Chain stored in ``audit.audit_event``; ``seq`` is a unique index that exposes forks."""

    def __init__(self, connection: AsyncSurrealConnection) -> None:
        self._connection = connection
        self._lock = asyncio.Lock()

    async def append(self, draft: AuditDraft) -> AuditEvent:
        """Seal ``draft`` onto the chain, retrying when another writer took the same ``seq``."""
        async with self._lock:
            for _ in range(_MAX_ATTEMPTS):
                seq, prev_hash = await self._head()
                event = seal(draft, seq=seq + 1, prev_hash=prev_hash)
                try:
                    created = await rows(
                        self._connection,
                        "CREATE audit_event CONTENT $event;",
                        {"event": _storable(event)},
                    )
                except ValidationError:
                    continue  # unique(seq) conflict: re-read the head and try again
                if not created:
                    raise AuditWriteError("audit write was rejected (check the writer's access)")
                return event
        raise AuditWriteError("could not append to the audit chain after several attempts")

    async def read_all(self) -> list[AuditEvent]:
        """Return every event ordered by ``seq``."""
        found = await rows(
            self._connection,
            f"SELECT {_COLUMNS} FROM audit_event ORDER BY seq;",  # noqa: S608 - constant columns
        )
        return [AuditEvent.model_validate(row) for row in found]

    async def _head(self) -> tuple[int, str]:
        found = await rows(
            self._connection, "SELECT seq, hash FROM audit_event ORDER BY seq DESC LIMIT 1;"
        )
        return (int(found[0]["seq"]), str(found[0]["hash"])) if found else (0, GENESIS_HASH)


def _storable(event: AuditEvent) -> dict[str, Any]:
    """Drop ``None`` fields: SurrealDB ``option<>`` fields take NONE, not NULL."""
    return {key: value for key, value in event.model_dump().items() if value is not None}
