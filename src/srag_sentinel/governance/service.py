"""CLI-facing audit operations: verify the chain and export it as JSONL."""

from pathlib import Path

from srag_sentinel.db.client import open_connection
from srag_sentinel.governance.chain import VerifyResult, verify_chain
from srag_sentinel.governance.model import AuditEvent
from srag_sentinel.governance.store import SurrealAuditStore
from srag_sentinel.settings import Settings


async def read_chain(settings: Settings) -> list[AuditEvent]:
    """Read the whole chain with the read-only audit user."""
    auth = {
        "namespace": settings.surreal_namespace,
        "database": settings.surreal_audit_database,
        "username": settings.surreal_audit_reader_user,
        "password": settings.surreal_audit_reader_password.get_secret_value(),
    }
    async with open_connection(
        settings.surreal_url,
        auth=auth,
        namespace=settings.surreal_namespace,
        database=settings.surreal_audit_database,
    ) as connection:
        return await SurrealAuditStore(connection).read_all()


async def verify(settings: Settings, *, expected_head: str | None = None) -> VerifyResult:
    """Verify the stored chain, optionally against an externally kept head hash."""
    return verify_chain(await read_chain(settings), expected_head=expected_head)


def export_jsonl(events: list[AuditEvent], target: Path) -> str | None:
    """Write ``events`` as JSON lines and return the head hash (keep it outside the database)."""
    lines = [event.model_dump_json() for event in events]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return events[-1].hash if events else None
