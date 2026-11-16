"""Thin helpers around the SurrealDB async SDK (remote WebSocket mode only)."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from surrealdb import AsyncSurreal, AsyncSurrealConnection


@asynccontextmanager
async def open_connection(
    url: str,
    *,
    auth: Mapping[str, Any],
    namespace: str | None = None,
    database: str | None = None,
) -> AsyncIterator[AsyncSurrealConnection]:
    """Open a connection, sign in with ``auth`` and optionally select a namespace/database."""
    connection = AsyncSurreal(url)
    try:
        await connection.signin(dict(auth))
        if namespace is not None and database is not None:
            await connection.use(namespace, database)
        yield connection
    finally:
        await connection.close()


async def run(
    connection: AsyncSurrealConnection,
    sql: str,
    variables: Mapping[str, Any] | None = None,
) -> list[Any]:
    """Execute SurrealQL with bound variables and return one result per statement.

    Values must always travel as ``variables``; never format them into ``sql``. Note that
    SurrealDB answers permission denials with an empty result instead of raising.
    """
    return list(await connection.query(sql, dict(variables or {})))


def surql_string(value: str) -> str:
    """Return ``value`` as a single-quoted SurrealQL string literal.

    Only for the few statements that cannot take variables (``DEFINE USER ... PASSWORD``) and
    only for administrator-supplied secrets, never for request data. Control characters are
    rejected; backslashes and quotes are escaped.
    """
    if any(char < " " or char == "\x7f" for char in value):
        raise ValueError("control characters are not allowed in SurrealQL string literals")
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


async def rows(
    connection: AsyncSurrealConnection,
    sql: str,
    variables: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a single-statement query and return its rows."""
    results = await run(connection, sql, variables)
    return list(results[0]) if results else []
