import pytest

from srag_sentinel import __version__
from srag_sentinel.cli import main
from srag_sentinel.settings import Settings


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_cli_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_cli_without_arguments_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: srag-sentinel" in capsys.readouterr().out


def test_settings_read_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SRAG_SURREAL_URL", "ws://db:8000/rpc")
    monkeypatch.setenv("SRAG_SURREAL_INGEST_PASSWORD", "s3cret")

    settings = Settings(_env_file=None)

    assert settings.surreal_url == "ws://db:8000/rpc"
    assert "s3cret" not in repr(settings)
    assert settings.surreal_ingest_password.get_secret_value() == "s3cret"
