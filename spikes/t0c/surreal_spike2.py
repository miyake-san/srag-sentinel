"""T0c follow-up: verify real state after role-restricted writes (results were ambiguous)."""

import asyncio
import sys
from datetime import datetime, timezone
from typing import Any

from surrealdb import AsyncSurreal

URL = "ws://127.0.0.1:18000/rpc"
NS = "srag"


async def run(db: Any, sql: str, vars: dict[str, Any] | None = None) -> Any:
    try:
        res = await db.query(sql, vars or {})
        return res.execute() if hasattr(res, "execute") else res
    except Exception as exc:  # noqa: BLE001
        return f"RAISED {type(exc).__name__}: {str(exc)[:150]}"


async def conn(auth: dict[str, Any], database: str) -> Any:
    db = AsyncSurreal(URL)
    await db.signin(auth)
    await db.use(NS, database)
    return db


async def main() -> None:
    root = await conn({"username": "root", "password": "spike-root-pw"}, "data")
    ro = await conn({"namespace": NS, "database": "data", "username": "api_ro", "password": "spike-ro"}, "data")
    print("whoami api_ro:", await run(ro, "RETURN $auth; RETURN $session.rd; RETURN $session.ac"))

    before = await run(root, "SELECT count() AS n, math::sum(cases) AS cases FROM srag_daily GROUP ALL")
    print("data before:", before)
    print("ro CREATE :", await run(ro, "CREATE srag_daily SET uf='X', day=time::now(), cases=1, deaths=0"))
    print("ro UPDATE :", await run(ro, "UPDATE srag_daily SET cases = 999"))
    print("ro DELETE :", await run(ro, "DELETE srag_daily WHERE uf = 'RJ'"))
    after = await run(root, "SELECT count() AS n, math::sum(cases) AS cases FROM srag_daily GROUP ALL")
    print("data after :", after, "-> unchanged" if before == after else "-> CHANGED")

    # audit side
    await root.use(NS, "audit")
    print("audit rows (root):", await run(root, "SELECT seq, hash FROM audit_event ORDER BY seq"))
    reader = await conn({"namespace": NS, "database": "audit", "username": "audit_reader", "password": "spike-reader"}, "audit")
    print("whoami reader:", await run(reader, "RETURN $session.rd; RETURN $session.ac; RETURN $auth"))
    print("reader CREATE seq=3:", await run(reader, "CREATE audit_event SET seq=3, hash='h3', prev_hash='h2', payload={k:'v'}"))
    print("audit rows (root):", await run(root, "SELECT seq, hash FROM audit_event ORDER BY seq"))

    editor = await conn({"namespace": NS, "database": "audit", "username": "audit_editor", "password": "spike-editor"}, "audit")
    print("editor DELETE seq=3:", await run(editor, "DELETE audit_event WHERE seq = 3"))
    print("audit rows (root):", await run(root, "SELECT seq, hash FROM audit_event ORDER BY seq"))

    # Variant: make the DB user a VIEWER and also set explicit table permissions for system users? (informational)
    print("INFO table def:", await run(root, "INFO FOR TABLE audit_event"))
    for c in (root, ro, reader, editor):
        await c.close()


asyncio.run(main())
sys.exit(0)
