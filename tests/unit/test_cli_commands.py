"""CLI command handlers with their collaborators replaced (no database, network or model)."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from srag_sentinel import cli
from srag_sentinel.agent.state import ReportState
from srag_sentinel.governance.chain import VerifyResult
from srag_sentinel.llm.factory import LLMConfigError
from srag_sentinel.service import RunResult


def test_no_command_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_db_init_reports_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def ok(_settings: Any) -> None:
        return None

    monkeypatch.setattr(cli, "init_database", ok)
    assert cli.main(["db", "init"]) == 0
    assert "initialised" in capsys.readouterr().out

    async def broken(_settings: Any) -> None:
        raise cli.SchemaInitError("missing required secrets: X")

    monkeypatch.setattr(cli, "init_database", broken)
    assert cli.main(["db", "init"]) == 2
    assert "missing required secrets" in capsys.readouterr().out


def test_audit_verify_exit_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def good(_settings: Any, *, expected_head: str | None = None) -> VerifyResult:
        return VerifyResult(ok=True, checked=3, head_hash="abc")

    async def bad(_settings: Any, *, expected_head: str | None = None) -> VerifyResult:
        return VerifyResult(ok=False, checked=3, head_hash="abc", failed_seq=2, reason="hash")

    monkeypatch.setattr(cli, "verify", good)
    assert cli.main(["audit", "verify"]) == 0
    assert "audit chain ok" in capsys.readouterr().out
    monkeypatch.setattr(cli, "verify", bad)
    assert cli.main(["audit", "verify", "--expected-head", "abc"]) == 1
    assert "BROKEN at seq 2" in capsys.readouterr().out


def test_audit_export_writes_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    async def nothing(_settings: Any) -> list[Any]:
        return []

    monkeypatch.setattr(cli, "read_chain", nothing)
    target = tmp_path / "audit.jsonl"

    assert cli.main(["audit", "export", "--out", str(target)]) == 0
    assert target.exists() and "exported 0 events" in capsys.readouterr().out


def test_metrics_command_rejects_bad_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["metrics", "--uf", "XX'; --"]) == 2
    assert "error" in capsys.readouterr().out


def test_ingest_reports_source_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def failing(_years: list[int]) -> list[str]:
        raise cli.SourceDiscoveryError("portal unreachable")

    monkeypatch.setattr(cli, "resolve_sources", failing)

    assert cli.main(["ingest"]) == 2
    assert "portal unreachable" in capsys.readouterr().out


def test_default_years_cover_the_twelve_month_window() -> None:
    years = cli.default_years()

    assert years[1] - years[0] == 1


class FakeService:
    def __init__(self, result: RunResult | None = None, *, fail_start: bool = False) -> None:
        self._result = result
        self._fail_start = fail_start
        self.requests: list[dict[str, Any]] = []
        self.stopped = False

    async def start(self) -> None:
        if self._fail_start:
            raise LLMConfigError("anthropic: missing API key (ANTHROPIC_API_KEY)")

    async def stop(self) -> None:
        self.stopped = True

    async def generate(self, request: dict[str, Any]) -> RunResult:
        self.requests.append(request)
        assert self._result is not None
        return self._result


def install(monkeypatch: pytest.MonkeyPatch, service: FakeService) -> None:
    monkeypatch.setattr("srag_sentinel.service.ReportService", lambda _settings: service)


def test_report_prints_the_stored_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = RunResult("run-1", ReportState(run_id="run-1"), {"html": tmp_path / "report.html"})
    service = FakeService(result)
    install(monkeypatch, service)

    code = cli.main(["report", "--uf", "SP", "--as-of", "2026-11-01", "--window-days", "14"])

    assert code == 0 and service.stopped
    assert service.requests == [{"uf": "SP", "window_days": 14, "as_of": "2026-11-01"}]
    assert "html:" in capsys.readouterr().out


def test_report_exit_code_when_the_request_is_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rejected = RunResult("run-2", ReportState(run_id="run-2", rejected=True), {})
    install(monkeypatch, FakeService(rejected))

    assert cli.main(["report", "--uf", "SP"]) == 2
    assert "rejected" in capsys.readouterr().out


def test_report_explains_a_missing_model_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, FakeService(fail_start=True))

    assert cli.main(["report"]) == 2
    assert "missing API key" in capsys.readouterr().out


def test_serve_starts_uvicorn_with_the_given_address(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.update(kw))

    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "9000"]) == 0  # noqa: S104
    assert calls["host"] == "0.0.0.0" and calls["port"] == 9000  # noqa: S104


def test_the_as_of_option_parses_iso_dates() -> None:
    args = cli.build_parser().parse_args(["report", "--as-of", "2026-11-01"])

    assert args.as_of == date(2026, 11, 1)
