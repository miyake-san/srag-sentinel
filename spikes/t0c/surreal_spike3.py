"""T0c follow-up 2: restrict CREATE to the record-access writer so VIEWER readers cannot write."""

import asyncio
from typing import Any

from surrealdb import AsyncSurreal

URL = "ws://127.0.0.1:18000/rpc"
NS = "srag"


async def run(db: Any, sql: str, vars: dict[str, Any] | None = None) -> Any:
    try:
        res = await db.query(sql, vars or {})
        return res.execute() if hasattr(res, "execute") else res
    except Exception as exc:  # noqa: BLE001
        return f"RAISED {type(exc).__name__}: {str(exc)[:200]}"


async def sys_conn(auth: dict[str, Any], database: str) -> Any:
    db = AsyncSurreal(URL)
    await db.signin(auth)
    await db.use(NS, database)
    return db


async def main() -> None:
    root = await sys_conn({"username": "root", "password": "spike-root-pw"}, "audit")
    print("ALTER:", await run(root, "ALTER TABLE audit_event PERMISSIONS FOR select FULL FOR create WHERE $access = 'audit_writer' FOR update, delete NONE"))

    writer = AsyncSurreal(URL)
    await writer.signin({"namespace": NS, "database": "audit", "access": "audit_writer",
                         "variables": {"name": "app", "pass": "spike-audit"}})
    await writer.use(NS, "audit")
    reader = await sys_conn({"namespace": NS, "database": "audit", "username": "audit_reader", "password": "spike-reader"}, "audit")

    print("writer CREATE seq=10:", await run(writer, "CREATE audit_event SET seq=10, hash='h10', prev_hash='h2', payload={k:'v'}"))
    print("reader CREATE seq=11:", await run(reader, "CREATE audit_event SET seq=11, hash='h11', prev_hash='h10', payload={k:'v'}"))
    print("writer SELECT:", await run(writer, "SELECT seq FROM audit_event ORDER BY seq"))
    print("reader SELECT:", await run(reader, "SELECT seq FROM audit_event ORDER BY seq"))
    print("writer UPDATE:", await run(writer, "UPDATE audit_event SET seq = 99 WHERE seq = 10"))
    print("writer DELETE:", await run(writer, "DELETE audit_event WHERE seq = 10"))
    print("rows (root):", await run(root, "SELECT seq FROM audit_event ORDER BY seq"))
    # can the writer read the credential table?
    print("writer reads svc:", await run(writer, "SELECT * FROM svc"))
    for c in (root, writer, reader):
        await c.close()


asyncio.run(main())
