"""Idempotent database bootstrap: namespace, databases, schema files and role users."""

from importlib.resources import files

from pydantic import SecretStr
from surrealdb import AsyncSurrealConnection

from srag_sentinel.db.client import open_connection, run, surql_string
from srag_sentinel.settings import Settings


class SchemaInitError(RuntimeError):
    """Raised when the database cannot be initialised safely."""


def _schema(name: str) -> str:
    return files("srag_sentinel.db").joinpath("schema", f"{name}.surql").read_text(encoding="utf-8")


def _require_passwords(settings: Settings) -> None:
    required = {
        "SRAG_SURREAL_ROOT_PASSWORD": settings.surreal_root_password,
        "SRAG_SURREAL_INGEST_PASSWORD": settings.surreal_ingest_password,
        "SRAG_SURREAL_API_RO_PASSWORD": settings.surreal_api_ro_password,
        "SRAG_SURREAL_API_RW_PASSWORD": settings.surreal_api_rw_password,
    }
    missing = [name for name, secret in required.items() if not secret.get_secret_value()]
    if missing:
        raise SchemaInitError(f"missing required secrets: {', '.join(missing)}")


async def init_database(settings: Settings) -> None:
    """Create namespace/databases, apply schema files and (re)define role users.

    Identifiers come from validated settings (plain names); passwords are bound variables.
    """
    _require_passwords(settings)
    root = {
        "username": settings.surreal_root_user,
        "password": settings.surreal_root_password.get_secret_value(),
    }
    namespace = settings.surreal_namespace
    data_db = settings.surreal_data_database
    app_db = settings.surreal_app_database

    async with open_connection(settings.surreal_url, auth=root) as connection:
        await run(connection, f"DEFINE NAMESPACE IF NOT EXISTS {namespace};")
        await connection.use(namespace, None)
        await run(connection, f"DEFINE DATABASE IF NOT EXISTS {data_db};")
        await run(connection, f"DEFINE DATABASE IF NOT EXISTS {app_db};")

        await connection.use(namespace, data_db)
        await run(connection, _schema("data"))
        await _define_user(
            connection, settings.surreal_ingest_user, settings.surreal_ingest_password, "EDITOR"
        )
        await _define_user(
            connection, settings.surreal_api_ro_user, settings.surreal_api_ro_password, "VIEWER"
        )

        await connection.use(namespace, app_db)
        await run(connection, _schema("app"))
        await _define_user(
            connection, settings.surreal_api_rw_user, settings.surreal_api_rw_password, "EDITOR"
        )


async def _define_user(
    connection: AsyncSurrealConnection, name: str, password: SecretStr, role: str
) -> None:
    """(Re)define a database user. ``DEFINE USER`` cannot take a variable for the password."""
    await run(
        connection,
        f"DEFINE USER OVERWRITE {name} ON DATABASE "
        f"PASSWORD {surql_string(password.get_secret_value())} ROLES {role};",
    )
