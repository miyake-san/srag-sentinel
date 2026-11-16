---
name: srag-testing
description: Testing conventions for srag-sentinel — pytest layout and markers, hypothesis property tests for metrics, respx-mocked HTTP for news providers, fake LLM, adversarial guardrail corpus, SurrealDB integration tests in a container, coverage and mypy gates. Use when writing or reviewing tests or CI quality gates.
---

# srag-sentinel · Testing

Spec: `SPEC.md` §6. Pair with the vendored `ruff` and `uv` skills for lint/run commands.

## Layout and markers
`tests/unit`, `tests/integration`, `tests/guardrails`, `tests/e2e`, `tests/fixtures`. Marker `live` (needs network/API key) is excluded by default; `integration` needs the SurrealDB container.

## Rules
- Write the failing test first for metrics and guardrails (red → green → refactor).
- Metrics: hand-built fixture with **independently computed** expected values; hypothesis properties (rates in [0,1], daily sum = window total, windows disjoint); `None` — never 0 — when the denominator is 0.
- Guardrails: table-driven adversarial corpus (prompt injection PT/EN + hidden Unicode, invented numbers, fake URLs, PII, invalid params, budget overflow) and a **fail-closed regression** (lying fake LLM ⇒ degraded report with no narrative text).
- HTTP adapters (GDELT/Tavily): mock with `respx`; no real network in default runs.
- LLM: deterministic fake chat model returning recorded structured outputs; never assert on free-form prose, assert on schema and grounding.
- SurrealDB: integration tests against a real container (Compose service or testcontainers); assert that `api_ro` cannot write to `data`/`audit` and that audit tampering is detected.
- Gates: `ruff check`, `ruff format --check`, `mypy --strict src`, `pytest --cov --cov-fail-under=85` (≥95% in `domain/` and `guardrails/`). Never weaken a test or threshold to get green.

## References (verified 2026-11-16)
- pytest — https://docs.pytest.org/en/stable/ · pytest-cov — https://pytest-cov.readthedocs.io/
- Hypothesis — https://hypothesis.readthedocs.io/
- respx (httpx mocking) — https://lundberg.github.io/respx/
- testcontainers-python — https://testcontainers-python.readthedocs.io/
- mypy — https://mypy.readthedocs.io/
- LangGraph testing — https://docs.langchain.com/oss/python/langgraph/test
