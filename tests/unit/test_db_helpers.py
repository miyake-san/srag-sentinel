import pytest
from pydantic import ValidationError

from srag_sentinel.db.client import surql_string
from srag_sentinel.db.init import SchemaInitError, init_database
from srag_sentinel.settings import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain", "'plain'"),
        ("it's", "'it\\'s'"),
        ("back\\slash", "'back\\\\slash'"),
        ("quote'; REMOVE TABLE x; --", "'quote\\'; REMOVE TABLE x; --'"),
        ("ação", "'ação'"),
    ],
)
def test_surql_string_escapes_quotes_and_backslashes(raw: str, expected: str) -> None:
    assert surql_string(raw) == expected


@pytest.mark.parametrize("raw", ["line\nbreak", "tab\there", "nul\x00", "del\x7f"])
def test_surql_string_rejects_control_characters(raw: str) -> None:
    with pytest.raises(ValueError, match="control"):
        surql_string(raw)


async def test_init_database_refuses_to_run_without_passwords() -> None:
    settings = Settings(_env_file=None)

    with pytest.raises(SchemaInitError, match="SRAG_SURREAL_ROOT_PASSWORD"):
        await init_database(settings)


@pytest.mark.parametrize("name", ["Data", "1data", "da-ta", "data; REMOVE", "x" * 40])
def test_settings_reject_unsafe_identifiers(name: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, surreal_namespace=name)
