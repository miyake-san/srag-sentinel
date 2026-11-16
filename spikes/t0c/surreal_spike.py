"""T0c spike: SurrealDB v4 + Python SDK 3 — roles, parameterized aggregation, append-only audit.

Throwaway test credentials only. Prints PASS/FAIL/INFO per check.
"""

import asyncio
import sys
from typing import Any

from surrealdb import AsyncSurreal

URL = "ws://127.0.0.1:18000/rpc"
NS = "srag"
ROOT = {"username": "root", "password": "spike-root-pw"}
RESULTS: list[tuple[str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name))
    print(f"{status} {name} {detail}".rstrip())


async def run(db: Any, sql: str, vars: dict[str, Any] | None = None) -> Any:
    res = await db.query(sql, vars or {})
    return res.execute() if hasattr(res, "execute") else res


async def attempt(db: Any, sql: str, vars: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Return (succeeded, repr). Errors may be raised or embedded in the result."""
    try:
        res = await run(db, sql, vars)
    except Exception as exc:  # noqa: BLE001 - spike inspects any failure
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"
    text = repr(res)
    low = text.lower()
    embedded_error = "error" in low and ("permission" in low or "error" in low[:80])
    return (not embedded_error), text[:200]


async def connect(auth: dict[str, Any], database: str | None) -> Any:
    db = AsyncSurreal(URL)
    await db.connect()  # url already given to constructor
    await db.signin(auth)
    if database is not None and "access" not in auth:
        await db.use(NS, database)
    return db


async def main() -> int:
    root = AsyncSurreal(URL)
    await root.signin(ROOT)
    await root.use(NS, "data")

    # --- schema ---------------------------------------------------------------------
    setup_data = """
    DEFINE TABLE srag_daily SCHEMAFULL;
    DEFINE FIELD uf ON srag_daily TYPE string;
    DEFINE FIELD day ON srag_daily TYPE datetime;
    DEFINE FIELD cases ON srag_daily TYPE int;
    DEFINE FIELD deaths ON srag_daily TYPE int;
    DEFINE INDEX uf_day ON srag_daily FIELDS uf, day UNIQUE;
    DEFINE USER ingest ON DATABASE PASSWORD 'spike-ingest' ROLES EDITOR;
    DEFINE USER api_ro ON DATABASE PASSWORD 'spike-ro' ROLES VIEWER;
    """
    ok, detail = await attempt(root, setup_data)
    record("PASS" if ok else "FAIL", "data: schema + users defined", detail if not ok else "")

    await root.use(NS, "audit")
    setup_audit = """
    DEFINE TABLE svc SCHEMAFULL PERMISSIONS NONE;
    DEFINE FIELD name ON svc TYPE string;
    DEFINE FIELD pass ON svc TYPE string;
    DEFINE TABLE audit_event SCHEMAFULL
      PERMISSIONS FOR select, create FULL FOR update, delete NONE;
    DEFINE FIELD seq ON audit_event TYPE int READONLY;
    DEFINE FIELD hash ON audit_event TYPE string READONLY;
    DEFINE FIELD prev_hash ON audit_event TYPE string READONLY;
    DEFINE FIELD payload ON audit_event TYPE object FLEXIBLE READONLY;
    DEFINE INDEX seq_uq ON audit_event FIELDS seq UNIQUE;
    DEFINE ACCESS audit_writer ON DATABASE TYPE RECORD
      SIGNIN (SELECT * FROM svc WHERE name = $name AND crypto::argon2::compare(pass, $pass))
      DURATION FOR TOKEN 15m, FOR SESSION 1h;
    CREATE svc SET name = 'app', pass = crypto::argon2::generate('spike-audit');
    DEFINE USER audit_editor ON DATABASE PASSWORD 'spike-editor' ROLES EDITOR;
    DEFINE USER audit_reader ON DATABASE PASSWORD 'spike-reader' ROLES VIEWER;
    """
    ok, detail = await attempt(root, setup_audit)
    record("PASS" if ok else "FAIL", "audit: schema + record access + users defined", detail if not ok else "")

    # --- data DB: ingest user, idempotent upsert, parameterized aggregation ---------------
    ingest = await connect({"namespace": NS, "database": "data", "username": "ingest", "password": "spike-ingest"}, "data")
    upsert = """
    UPSERT srag_daily:[$uf, $day] SET uf = $uf, day = $day, cases = $cases, deaths = $deaths;
    """
    from datetime import datetime, timezone

    rows = [("SP", datetime(2026, 11, 14, tzinfo=timezone.utc), 10, 1),
            ("SP", datetime(2026, 11, 15, tzinfo=timezone.utc), 12, 2),
            ("RJ", datetime(2026, 11, 15, tzinfo=timezone.utc), 5, 0)]
    for _ in range(2):  # twice -> idempotent
        for uf, day, cases, deaths in rows:
            ok, detail = await attempt(ingest, upsert, {"uf": uf, "day": day, "cases": cases, "deaths": deaths})
            if not ok:
                record("FAIL", "data: ingest upsert", detail)
    count = await run(ingest, "SELECT count() AS n FROM srag_daily GROUP ALL")
    record("PASS" if "3" in repr(count) else "FAIL", "data: upsert idempotent (expect 3 rows)", repr(count)[:120])

    agg = ("SELECT math::sum(cases) AS cases, math::sum(deaths) AS deaths FROM srag_daily "
           "WHERE day >= $start AND day <= $end AND ($uf = 'BR' OR uf = $uf) GROUP ALL")
    window = {"start": datetime(2026, 11, 1, tzinfo=timezone.utc), "end": datetime(2026, 11, 30, tzinfo=timezone.utc)}
    for uf, expected in [("BR", "27"), ("SP", "22")]:
        res = await run(ingest, agg, {**window, "uf": uf})
        record("PASS" if expected in repr(res) else "FAIL", f"data: aggregate with variables uf={uf} (expect cases={expected})", repr(res)[:140])

    # injection-shaped parameter must be inert
    res = await run(ingest, agg, {**window, "uf": "BR'; REMOVE TABLE srag_daily; --"})
    still = await run(ingest, "SELECT count() AS n FROM srag_daily GROUP ALL")
    record("PASS" if "3" in repr(still) else "FAIL", "data: injection-shaped param inert (table intact)", repr(still)[:100])

    # api_ro: read yes, write no
    ro = await connect({"namespace": NS, "database": "data", "username": "api_ro", "password": "spike-ro"}, "data")
    ok, detail = await attempt(ro, "SELECT * FROM srag_daily LIMIT 1")
    record("PASS" if ok else "FAIL", "data: api_ro can SELECT", detail if not ok else "")
    for label, sql in [("CREATE", "CREATE srag_daily SET uf='X', day=time::now(), cases=1, deaths=0"),
                       ("UPDATE", "UPDATE srag_daily SET cases = 999"),
                       ("DELETE", "DELETE srag_daily")]:
        ok, detail = await attempt(ro, sql)
        record("PASS" if not ok else "FAIL", f"data: api_ro {label} is rejected", detail)

    # --- audit DB: record access user (append-only) -----------------------------------------
    writer = await connect({"namespace": NS, "database": "audit", "access": "audit_writer",
                            "variables": {"name": "app", "pass": "spike-audit"}}, None)
    await writer.use(NS, "audit")
    ev = "CREATE audit_event SET seq = $seq, hash = $hash, prev_hash = $prev, payload = {k: 'v'}"
    ok, detail = await attempt(writer, ev, {"seq": 1, "hash": "h1", "prev": "genesis"})
    record("PASS" if ok else "FAIL", "audit: record-access writer can CREATE", detail if not ok else "")
    ok, detail = await attempt(writer, ev, {"seq": 1, "hash": "h1b", "prev": "genesis"})
    record("PASS" if not ok else "FAIL", "audit: duplicate seq rejected (UNIQUE)", detail)
    ok, detail = await attempt(writer, "SELECT * FROM audit_event")
    record("PASS" if ok else "FAIL", "audit: writer can SELECT", detail if not ok else "")
    for label, sql in [("UPDATE", "UPDATE audit_event SET payload = {k: 'tampered'}"),
                       ("DELETE", "DELETE audit_event")]:
        ok, detail = await attempt(writer, sql)
        after = await run(writer, "SELECT * FROM audit_event")
        intact = "v" in repr(after) and "tampered" not in repr(after) and "h1" in repr(after)
        record("PASS" if (not ok or intact) and intact else "FAIL",
               f"audit: writer {label} blocked (data intact={intact})", detail)

    # system EDITOR user: do table PERMISSIONS bind it? (spec assumption: they do NOT)
    editor = await connect({"namespace": NS, "database": "audit", "username": "audit_editor", "password": "spike-editor"}, "audit")
    ok, detail = await attempt(editor, "DELETE audit_event WHERE seq = 999")  # harmless no-op target
    record("INFO", "audit: system EDITOR DELETE accepted by server (permission bypass check)", f"accepted={ok} {detail}")
    ok, detail = await attempt(editor, "UPDATE audit_event SET hash = 'forged' WHERE seq = 1")
    after = await run(root, "SELECT hash FROM audit_event WHERE seq = 1")
    record("INFO", "audit: system EDITOR UPDATE of READONLY field", f"accepted={ok} hash_after={repr(after)[:100]}")

    # audit_reader (VIEWER)
    reader = await connect({"namespace": NS, "database": "audit", "username": "audit_reader", "password": "spike-reader"}, "audit")
    ok, detail = await attempt(reader, "SELECT * FROM audit_event")
    record("PASS" if ok else "FAIL", "audit: VIEWER reader can SELECT", detail if not ok else "")
    ok, detail = await attempt(reader, ev, {"seq": 2, "hash": "h2", "prev": "h1"})
    record("PASS" if not ok else "FAIL", "audit: VIEWER reader cannot CREATE", detail)

    for conn in (root, ingest, ro, writer, editor, reader):
        await conn.close()

    failed = [n for s, n in RESULTS if s == "FAIL"]
    print(f"\nSUMMARY: {sum(1 for s, _ in RESULTS if s == 'PASS')} PASS, {len(failed)} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
