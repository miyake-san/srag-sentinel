"""The composition root on a real SurrealDB with scripted models and no network."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from helpers import writer_connection

from srag_sentinel import cli
from srag_sentinel.agent.schemas import Claim, Narrative, NewsPlan
from srag_sentinel.data.repository import SurrealCountersWriter
from srag_sentinel.domain.models import DailyCounters
from srag_sentinel.governance.chain import verify_chain
from srag_sentinel.governance.service import read_chain
from srag_sentinel.llm.fake import ScriptedModel
from srag_sentinel.news.chain import ChainedNewsProvider
from srag_sentinel.news.fake import FakeNewsProvider
from srag_sentinel.service import ReportNotFoundError, ReportService
from srag_sentinel.settings import Settings

pytestmark = pytest.mark.integration

LYING = Narrative(
    summary="Foram 99999 casos.",
    metric_commentary=(Claim(text="Foram 99999 casos.", metric_refs=("M1",)),),
)


async def load_data(settings: Settings) -> None:
    today = datetime.now(UTC).date()
    rows = [
        DailyCounters(
            uf="SP",
            day=today - timedelta(days=offset),
            cases=10,
            hosp_cases=5,
            outcome_known=4,
            deaths=1,
            uti_known=4,
            uti_yes=1,
            vac_cov_known=8,
            vac_cov_yes=4,
            vac_flu_known=8,
            vac_flu_yes=3,
        )
        for offset in range(0, 90)
    ]
    async with writer_connection(settings) as db:
        await SurrealCountersWriter(db).upsert_daily(rows)


async def test_a_run_stores_artifacts_and_an_intact_audit_trail(
    settings: Settings, tmp_path: Path
) -> None:
    await load_data(settings)
    configured = settings.model_copy(update={"reports_dir": tmp_path})
    plan = NewsPlan(queries=["síndrome respiratória aguda grave"])
    service = ReportService(
        configured,
        large=ScriptedModel([plan, LYING, LYING], model_name="fake:large"),  # type: ignore[arg-type]
        judge=ScriptedModel([], model_name="fake:judge"),
        news=ChainedNewsProvider([FakeNewsProvider([])]),
    )
    await service.start()
    try:
        assert await service.ready()
        result = await service.generate({"uf": "SP"})

        assert result.status == "degraded"  # the lying narrative is rejected, never published
        assert result.state.report is not None and result.state.report.narrative is None
        assert {"html", "json"} <= set(result.files)
        assert service.artifact(result.run_id, "json").read_text().startswith("{")
        events = await service.audit_events(result.run_id)
        assert events and events[0].event == "run_start"
        with pytest.raises(ReportNotFoundError):
            service.artifact("../../etc/passwd", "json")
        with pytest.raises(ReportNotFoundError):
            service.artifact(result.run_id, "exe")
    finally:
        await service.stop()

    assert verify_chain(await read_chain(configured)).ok


async def test_a_rejected_request_writes_no_files(settings: Settings, tmp_path: Path) -> None:
    await load_data(settings)
    service = ReportService(
        settings.model_copy(update={"reports_dir": tmp_path}),
        large=ScriptedModel([], model_name="fake:large"),  # type: ignore[arg-type]
        judge=ScriptedModel([], model_name="fake:judge"),
        news=ChainedNewsProvider([FakeNewsProvider([])]),
    )
    await service.start()
    try:
        result = await service.generate({"uf": "XX'; REMOVE TABLE x"})
    finally:
        await service.stop()

    assert result.rejected and result.files == {}
    assert list(tmp_path.iterdir()) == []


def test_kg_prune_command_runs_against_the_real_graph(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main(["kg", "prune"]) == 0
    assert "pruned 0 expired node(s)" in capsys.readouterr().out
