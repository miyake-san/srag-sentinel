import pytest

from srag_sentinel.cli import main
from srag_sentinel.data.ingest.service import PartialIngestError, ingest
from srag_sentinel.settings import Settings


async def test_a_single_yearly_file_is_refused_by_default() -> None:
    with pytest.raises(PartialIngestError, match="two yearly files"):
        await ingest(Settings(_env_file=None), ["2026.parquet"])


async def test_nothing_to_ingest_is_also_refused() -> None:
    with pytest.raises(PartialIngestError):
        await ingest(Settings(_env_file=None), [])


def test_cli_reports_the_refusal_and_the_escape_hatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("srag_sentinel.cli.get_settings", lambda: Settings(_env_file=None))

    assert main(["ingest", "--url", "only-one.parquet"]) == 2
    assert "--allow-partial" in capsys.readouterr().out
