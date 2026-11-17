"""API routes with a fake service: no database, models or network."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from srag_sentinel.agent.state import ReportState
from srag_sentinel.api.app import create_app
from srag_sentinel.governance.chain import seal
from srag_sentinel.governance.model import GENESIS_HASH, AuditDraft, AuditEvent
from srag_sentinel.service import ReportNotFoundError, RunResult
from srag_sentinel.settings import Settings
from support_report import make_draft, make_narrative

RUN_ID = "11111111-2222-3333-4444-555555555555"


def open_app(service: Any) -> Any:
    """The app in dev mode without keys, whatever the developer's own ``.env`` holds."""
    return create_app(Settings(_env_file=None, environment="dev"), service=service)  # type: ignore[call-arg]


class FakeService:
    def __init__(self, tmp_path: Path, *, ready: bool = True, rejected: bool = False) -> None:
        self._dir = tmp_path
        self._ready = ready
        self._rejected = rejected
        self.requests: list[dict[str, Any]] = []
        self.started = self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def ready(self) -> bool:
        return self._ready

    async def generate(self, raw_request: dict[str, Any]) -> RunResult:
        self.requests.append(raw_request)
        if self._rejected:
            return RunResult(RUN_ID, ReportState(run_id=RUN_ID, rejected=True), {})
        draft = make_draft(narrative=make_narrative())
        folder = self._dir / RUN_ID
        folder.mkdir(exist_ok=True)
        files = {}
        for fmt, content in {"json": "{}", "html": "<html></html>"}.items():
            path = folder / f"report.{fmt}"
            path.write_text(content)
            files[fmt] = path
        return RunResult(RUN_ID, ReportState(run_id=RUN_ID, report=draft), files)

    def artifact(self, run_id: str, fmt: str) -> Path:
        path = self._dir / run_id / f"report.{fmt}"
        if not path.is_file():
            raise ReportNotFoundError(run_id)
        return path

    async def audit_events(self, run_id: str) -> list[AuditEvent]:
        if run_id != RUN_ID:
            return []
        draft = AuditDraft(
            run_id=RUN_ID, actor="system", node="run", event="run_start", details={"a": 1}
        )
        return [seal(draft, seq=1, prev_hash=GENESIS_HASH)]


@pytest.fixture
def service(tmp_path: Path) -> FakeService:
    return FakeService(tmp_path)


@pytest.fixture
def client(service: FakeService):  # type: ignore[no-untyped-def]
    with TestClient(open_app(service), raise_server_exceptions=False) as test_client:
        yield test_client


def test_lifespan_starts_and_stops_the_service(service: FakeService) -> None:
    with TestClient(open_app(service)):
        assert service.started and not service.stopped
    assert service.stopped


def test_health_and_readiness(client: TestClient, service: FakeService) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200
    service._ready = False
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


def test_creating_a_report_returns_links_and_passes_validated_input(
    client: TestClient, service: FakeService
) -> None:
    response = client.post("/v1/reports", json={"uf": "SP", "window_days": 14})

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == RUN_ID and body["status"] == "ok"
    assert body["links"]["html"] == f"/v1/reports/{RUN_ID}?format=html"
    assert service.requests == [{"uf": "SP", "window_days": 14}]


@pytest.mark.parametrize(
    "payload",
    [
        {"uf": "BR'; REMOVE TABLE x; --"},
        {"uf": "SP", "window_days": 500},
        {"uf": "SP", "extra": 1},
        {"as_of": "not-a-date"},
    ],
)
def test_invalid_requests_are_422_problems_that_do_not_echo_input(
    client: TestClient, payload: dict[str, Any]
) -> None:
    response = client.post("/v1/reports", json=payload)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "REMOVE TABLE" not in response.text and "not-a-date" not in response.text
    assert response.json()["errors"]


def test_a_guardrail_rejection_is_a_422_with_the_run_id(tmp_path: Path) -> None:
    with TestClient(open_app(FakeService(tmp_path, rejected=True))) as client:
        response = client.post("/v1/reports", json={"uf": "SP"})

    assert response.status_code == 422
    assert response.json()["run_id"] == RUN_ID


def test_reports_are_served_in_each_format(client: TestClient) -> None:
    client.post("/v1/reports", json={})

    assert client.get(f"/v1/reports/{RUN_ID}").headers["content-type"] == "application/json"
    html = client.get(f"/v1/reports/{RUN_ID}?format=html")
    assert html.headers["content-type"].startswith("text/html")
    assert html.headers["cache-control"] == "no-store"


def test_unknown_or_malicious_ids_and_formats(client: TestClient) -> None:
    assert client.get("/v1/reports/nope").status_code == 404
    assert client.get(f"/v1/reports/{RUN_ID}?format=pdf").status_code == 404  # not produced
    assert client.get(f"/v1/reports/{RUN_ID}?format=exe").status_code == 422
    assert client.get("/v1/reports/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_audit_endpoint_lists_events_without_content(client: TestClient) -> None:
    body = client.get(f"/v1/audit/{RUN_ID}").json()

    assert body["events"][0]["event"] == "run_start"
    assert "inputs_hash" not in body["events"][0]
    assert client.get("/v1/audit/unknown").status_code == 404


def test_unexpected_errors_are_opaque_500_problems(tmp_path: Path) -> None:
    class Broken(FakeService):
        async def generate(self, raw_request: dict[str, Any]) -> RunResult:
            raise RuntimeError("SELECT * FROM secret; password=hunter2")

    with TestClient(open_app(Broken(tmp_path)), raise_server_exceptions=False) as client:
        response = client.post("/v1/reports", json={})

    assert response.status_code == 500
    assert "hunter2" not in response.text and "SELECT" not in response.text
