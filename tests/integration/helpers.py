"""Connection helpers shared by the integration tests (one per database role)."""

from contextlib import AbstractAsyncContextManager

from surrealdb import AsyncSurrealConnection

from srag_sentinel.db.client import open_connection
from srag_sentinel.settings import Settings

Connection = AbstractAsyncContextManager[AsyncSurrealConnection]


def _data_connection(settings: Settings, user: str, password: str) -> Connection:
    return open_connection(
        settings.surreal_url,
        auth={
            "namespace": settings.surreal_namespace,
            "database": settings.surreal_data_database,
            "username": user,
            "password": password,
        },
        namespace=settings.surreal_namespace,
        database=settings.surreal_data_database,
    )


def writer_connection(settings: Settings) -> Connection:
    """Connection as the ingest (writer) user."""
    return _data_connection(
        settings, settings.surreal_ingest_user, settings.surreal_ingest_password.get_secret_value()
    )


def reader_connection(settings: Settings) -> Connection:
    """Connection as the read-only API user."""
    return _data_connection(
        settings, settings.surreal_api_ro_user, settings.surreal_api_ro_password.get_secret_value()
    )


def audit_writer_connection(settings: Settings) -> Connection:
    """Connection as the record-access audit writer (what the application uses)."""
    return open_connection(
        settings.surreal_url,
        auth={
            "namespace": settings.surreal_namespace,
            "database": settings.surreal_audit_database,
            "access": "audit_writer",
            "variables": {
                "name": settings.surreal_audit_writer_name,
                "pass": settings.surreal_audit_writer_password.get_secret_value(),
            },
        },
        namespace=settings.surreal_namespace,
        database=settings.surreal_audit_database,
    )


def audit_reader_connection(settings: Settings) -> Connection:
    """Read-only system user for ``audit verify`` and export."""
    return open_connection(
        settings.surreal_url,
        auth={
            "namespace": settings.surreal_namespace,
            "database": settings.surreal_audit_database,
            "username": settings.surreal_audit_reader_user,
            "password": settings.surreal_audit_reader_password.get_secret_value(),
        },
        namespace=settings.surreal_namespace,
        database=settings.surreal_audit_database,
    )


def audit_root_connection(settings: Settings) -> Connection:
    """Admin connection to the audit database, used to simulate tampering."""
    return open_connection(
        settings.surreal_url,
        auth={"username": "root", "password": settings.surreal_root_password.get_secret_value()},
        namespace=settings.surreal_namespace,
        database=settings.surreal_audit_database,
    )


def root_connection(settings: Settings) -> Connection:
    """Admin connection, used only to inspect the final state."""
    return open_connection(
        settings.surreal_url,
        auth={"username": "root", "password": settings.surreal_root_password.get_secret_value()},
        namespace=settings.surreal_namespace,
        database=settings.surreal_data_database,
    )
