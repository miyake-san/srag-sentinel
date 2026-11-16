---
name: srag-fastapi-pydantic
description: Conventions for the srag-sentinel HTTP API and data models — FastAPI (lifespan, dependency injection, RFC 9457 errors, health/readiness) and Pydantic v2 (frozen models, extra=forbid, pydantic-settings, SecretStr). Use when editing src/srag_sentinel/api, settings.py, or any Pydantic model/schema.
---

# srag-sentinel · FastAPI + Pydantic

Spec: `docs/specs/03-agent-and-tools.md` §6 (routes) and `docs/specs/04-guardrails-security.md` (G1).

## Rules
- App wiring (composition root) happens in the **lifespan**: build the DB client, LLM, news provider and OTel; store them on `app.state`; close them on shutdown. Routes get dependencies via `Depends`, never via globals.
- Request/response models: `ConfigDict(extra="forbid", frozen=True)`; constrained types (`Literal`/enum for UF, `date` bounds, `window_days` 7–90). Validation errors = G1 verdicts and are audited.
- Errors use `application/problem+json` (RFC 9457) with `run_id` and `trace_id`; never leak stack traces, SurrealQL or provider messages.
- `/healthz` = process alive; `/readyz` = DB reachable and data present. Both unauthenticated, no sensitive output.
- Settings: `pydantic-settings`, prefix `SRAG_`, validated at boot; secrets as `SecretStr` and excluded from `repr`/logs.
- Long work (graph run) must not block the event loop: use async clients end to end, or run blocking code in a threadpool.
- Test with `TestClient`/`httpx.AsyncClient` and dependency overrides (fake LLM, fake news, in-memory repo).

## References (verified 2026-11-16)
- FastAPI — https://fastapi.tiangolo.com/
- Lifespan events — https://fastapi.tiangolo.com/advanced/events/
- Testing — https://fastapi.tiangolo.com/tutorial/testing/
- Pydantic v2 — https://docs.pydantic.dev/latest/
- pydantic-settings — https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- Problem Details (RFC 9457) — https://www.rfc-editor.org/rfc/rfc9457
