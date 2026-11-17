"""API perimeter (docs/specs/09 §3, A1-A7): keys, limits, body size, headers, audit output."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_api_routes import RUN_ID, FakeService

from srag_sentinel.api.app import create_app
from srag_sentinel.api.perimeter import HTML_CSP, Perimeter
from srag_sentinel.governance.chain import seal
from srag_sentinel.governance.model import GENESIS_HASH, AuditDraft
from srag_sentinel.settings import Settings

KEY = "test-key-one"
OTHER_KEY = "test-key-two"
AUTH = {"Authorization": f"Bearer {KEY}"}


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"environment": "dev", "api_keys": SecretStr(f"{KEY},{OTHER_KEY}")}
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[arg-type]


@pytest.fixture
def client(tmp_path: Path):  # type: ignore[no-untyped-def]
    app = create_app(make_settings(), service=FakeService(tmp_path))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_routes_need_a_valid_bearer_key(client: TestClient) -> None:
    assert client.post("/v1/reports", json={}).status_code == 401
    assert client.get(f"/v1/audit/{RUN_ID}").status_code == 401
    bad = client.post("/v1/reports", json={}, headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    assert bad.headers["www-authenticate"] == "Bearer"
    assert bad.headers["content-type"].startswith("application/problem+json")
    assert "nope" not in bad.text
    wrong_scheme = client.post("/v1/reports", json={}, headers={"Authorization": f"Basic {KEY}"})
    assert wrong_scheme.status_code == 401


def test_every_configured_key_is_accepted(client: TestClient) -> None:
    assert client.post("/v1/reports", json={}, headers=AUTH).status_code == 200
    other = {"Authorization": f"Bearer {OTHER_KEY}"}
    assert client.post("/v1/reports", json={}, headers=other).status_code == 200


def test_health_probes_stay_public(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_a_missing_key_list_stops_the_boot_outside_dev(tmp_path: Path) -> None:
    for environment in ("prod", "test"):
        settings = make_settings(environment=environment, api_keys=SecretStr(""))
        with pytest.raises(RuntimeError, match="SRAG_API_KEYS"):
            create_app(settings, service=FakeService(tmp_path))


def test_dev_without_keys_runs_open(tmp_path: Path) -> None:
    app = create_app(make_settings(api_keys=SecretStr("")), service=FakeService(tmp_path))
    with TestClient(app) as open_client:
        assert open_client.post("/v1/reports", json={}).status_code == 200


def test_rate_limit_returns_429_with_retry_after_and_recovers(tmp_path: Path) -> None:
    now = [1000.0]
    app = create_app(make_settings(api_rate_per_minute=2), service=FakeService(tmp_path))
    middleware_perimeter = _perimeter_of(app)
    middleware_perimeter.clock = lambda: now[0]
    with TestClient(app) as test_client:
        assert test_client.post("/v1/reports", json={}, headers=AUTH).status_code == 200
        assert test_client.post("/v1/reports", json={}, headers=AUTH).status_code == 200
        limited = test_client.post("/v1/reports", json={}, headers=AUTH)
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1
        other = {"Authorization": f"Bearer {OTHER_KEY}"}
        assert test_client.post("/v1/reports", json={}, headers=other).status_code == 200
        now[0] += 61
        assert test_client.post("/v1/reports", json={}, headers=AUTH).status_code == 200


def test_the_concurrency_cap_refuses_instead_of_queueing() -> None:
    perimeter = Perimeter(keys=(), rate_per_minute=10, max_concurrent=2, max_body_bytes=1024)

    assert perimeter.acquire() and perimeter.acquire()
    assert not perimeter.acquire()
    perimeter.release()
    assert perimeter.acquire()


def test_a_busy_process_answers_429(tmp_path: Path) -> None:
    app = create_app(make_settings(api_max_concurrent=1), service=FakeService(tmp_path))
    assert _perimeter_of(app).acquire()  # another report is already running
    with TestClient(app) as test_client:
        response = test_client.post("/v1/reports", json={}, headers=AUTH)
    assert response.status_code == 429 and "retry-after" in response.headers


def test_the_slot_is_released_after_a_failed_request(tmp_path: Path) -> None:
    class Broken(FakeService):
        async def generate(self, raw_request):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    app = create_app(make_settings(api_max_concurrent=1), service=Broken(tmp_path))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        for _ in range(2):
            assert test_client.post("/v1/reports", json={}, headers=AUTH).status_code == 500


def test_oversized_and_non_json_bodies_are_refused(client: TestClient) -> None:
    big = client.post("/v1/reports", content='{"uf":"' + "A" * 2000 + '"}', headers=_json(AUTH))
    assert big.status_code == 413
    text = client.post(
        "/v1/reports", content='{"uf":"SP"}', headers={**AUTH, "Content-Type": "text/plain"}
    )
    assert text.status_code == 415
    assert client.post("/v1/reports", json={"uf": "SP"}, headers=AUTH).status_code == 200


def test_streamed_bodies_are_capped_without_a_content_length(client: TestClient) -> None:
    def chunks():  # type: ignore[no-untyped-def]
        for _ in range(10):
            yield b" " * 300

    response = client.post("/v1/reports", content=chunks(), headers=_json(AUTH))
    assert response.status_code == 413


def test_security_headers_are_on_every_response(client: TestClient) -> None:
    client.post("/v1/reports", json={}, headers=AUTH)
    for response in (
        client.get("/healthz"),
        client.get(f"/v1/reports/{RUN_ID}", headers=AUTH),
        client.get("/v1/reports/nope", headers=AUTH),
        client.post("/v1/reports", json={}),
    ):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"


def test_the_html_report_carries_a_csp(client: TestClient) -> None:
    client.post("/v1/reports", json={}, headers=AUTH)
    html = client.get(f"/v1/reports/{RUN_ID}?format=html", headers=AUTH)
    assert html.headers["content-security-policy"] == HTML_CSP


def test_audit_output_is_counters_only(tmp_path: Path) -> None:
    class Chatty(FakeService):
        async def audit_events(self, run_id: str):  # type: ignore[no-untyped-def]
            draft = AuditDraft(
                run_id=RUN_ID,
                actor="system",
                node="n",
                event="decision",
                details={"count": 3, "note": "free text", "flag": True},
            )
            return [seal(draft, seq=1, prev_hash=GENESIS_HASH)]

    app = create_app(make_settings(), service=Chatty(tmp_path))
    with TestClient(app) as test_client:
        event = test_client.get(f"/v1/audit/{RUN_ID}", headers=AUTH).json()["events"][0]
    assert event["details"] == {"count": 3}
    assert "actor" not in event


def test_refusals_are_counted_by_reason(tmp_path: Path) -> None:
    app = create_app(make_settings(), service=FakeService(tmp_path))
    reasons: list[str] = []
    perimeter = _perimeter_of(app)
    with TestClient(app) as test_client:
        perimeter.on_reject = reasons.append  # the lifespan installed the telemetry hook
        test_client.post("/v1/reports", json={})
        test_client.post("/v1/reports", content="x", headers={**AUTH, "Content-Type": "text/plain"})
    assert reasons == ["unauthorized", "unsupported_media_type"]
    assert KEY not in repr(reasons)


def test_only_the_exact_key_is_accepted_and_identity_hides_it() -> None:
    perimeter = Perimeter(keys=(KEY,), rate_per_minute=10, max_concurrent=1, max_body_bytes=1024)

    identity = perimeter.identify(f"Bearer {KEY}", "127.0.0.1")
    assert identity is not None and KEY not in identity
    assert perimeter.identify(f"Bearer {KEY}x", "127.0.0.1") is None
    assert perimeter.identify("Bearer", "127.0.0.1") is None
    assert perimeter.identify(None, "127.0.0.1") is None


def _json(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Content-Type": "application/json"}


def _perimeter_of(app) -> Perimeter:  # type: ignore[no-untyped-def]
    for middleware in app.user_middleware:
        perimeter = middleware.kwargs.get("perimeter")
        if isinstance(perimeter, Perimeter):
            return perimeter
    raise AssertionError("perimeter middleware not installed")
