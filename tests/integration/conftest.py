"""Integration fixtures: a throwaway namespace per test on a running SurrealDB.

Start the database with (any throwaway password):
    SURREAL_ROOT_PASSWORD=<pw> docker compose -f compose.yaml -f compose.dev.yaml \\
        up -d surrealdb
and run:  SURREAL_ROOT_PASSWORD=<same pw> uv run pytest -m integration
"""

import os
import secrets
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio

from srag_sentinel.db.client import open_connection, run
from srag_sentinel.db.init import init_database
from srag_sentinel.settings import Settings

SURREAL_URL = os.environ.get("SRAG_TEST_SURREAL_URL", "ws://127.0.0.1:8000/rpc")


@pytest_asyncio.fixture
async def settings() -> AsyncIterator[Settings]:
    root_password = os.environ.get("SURREAL_ROOT_PASSWORD")
    if not root_password:
        pytest.skip("SURREAL_ROOT_PASSWORD not set")
    test_settings = Settings(
        _env_file=None,
        surreal_url=SURREAL_URL,
        surreal_namespace=f"it_{uuid4().hex[:12]}",
        surreal_root_password=root_password,  # type: ignore[arg-type]
        # quote and backslash on purpose: exercises the literal escaping in `db init`
        surreal_ingest_password=secrets.token_urlsafe(16) + "'\\x",  # type: ignore[arg-type]
        surreal_api_ro_password=secrets.token_urlsafe(16),  # type: ignore[arg-type]
        surreal_api_rw_password=secrets.token_urlsafe(16),  # type: ignore[arg-type]
        surreal_audit_writer_password=secrets.token_urlsafe(16),  # type: ignore[arg-type]
        surreal_audit_reader_password=secrets.token_urlsafe(16),  # type: ignore[arg-type]
    )
    await init_database(test_settings)
    yield test_settings
    root = {"username": "root", "password": root_password}
    async with open_connection(SURREAL_URL, auth=root) as connection:
        await run(connection, f"REMOVE NAMESPACE IF EXISTS {test_settings.surreal_namespace};")
