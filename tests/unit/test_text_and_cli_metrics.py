from datetime import date

import pytest

from srag_sentinel.cli import main
from srag_sentinel.domain.metrics import compute_metrics
from srag_sentinel.domain.models import DailyCounters, MetricsPayload
from srag_sentinel.domain.series import SeriesPayload, daily_series, monthly_series
from srag_sentinel.reporting.text import format_metrics, format_series
from srag_sentinel.settings import Settings

AS_OF = date(2026, 11, 15)


def counters() -> list[DailyCounters]:
    return [
        DailyCounters(
            uf="SP",
            day=date(2026, 11, 10),
            cases=10,
            hosp_cases=8,
            outcome_known=4,
            deaths=1,
            uti_known=8,
            uti_yes=2,
            vac_cov_known=10,
            vac_cov_yes=5,
            vac_flu_known=10,
            vac_flu_yes=1,
        )
    ]


def payloads() -> tuple[MetricsPayload, SeriesPayload]:
    metrics = compute_metrics(counters(), as_of=AS_OF, window_days=30, scope="BR")
    cases = {date(2026, 11, 10): 10}
    series = SeriesPayload(
        scope="BR",
        as_of=AS_OF,
        daily=daily_series(cases, as_of=AS_OF),
        monthly=monthly_series(cases, as_of=AS_OF),
    )
    return metrics, series


def test_metrics_text_shows_every_metric_proxy_tags_and_not_computable_values() -> None:
    metrics, _ = payloads()

    text = format_metrics(metrics)

    assert "Taxa de aumento de casos" in text
    assert "Taxa de mortalidade" in text
    assert text.count("[proxy]") == 3  # ICU + two vaccination metrics
    assert "n/d" in text  # M1 has no previous window
    assert "25.0%" in text  # mortality 1/4


def test_series_text_has_thirty_daily_rows_and_marks_the_partial_month() -> None:
    _, series = payloads()

    text = format_series(series)

    assert text.count("\n  2026-") == 30 + 11  # 30 days + the 11 monthly rows of 2026
    assert "\n  2025-12" in text  # the twelfth (oldest) month
    assert "(parcial)" in text


def test_cli_metrics_prints_metrics_and_series(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_load(settings: Settings, args: object) -> tuple[MetricsPayload, SeriesPayload]:
        return payloads()

    monkeypatch.setattr("srag_sentinel.cli.get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr("srag_sentinel.cli.load_metrics_and_series", fake_load)

    assert main(["metrics", "--uf", "SP", "--as-of", "2026-11-15"]) == 0
    output = capsys.readouterr().out
    assert "Taxa de mortalidade" in output
    assert "Casos por mês" in output


def test_cli_metrics_rejects_an_invalid_uf(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["metrics", "--uf", "ZZ"]) == 2
    assert "error" in capsys.readouterr().out
