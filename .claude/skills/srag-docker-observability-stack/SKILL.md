---
name: srag-docker-observability-stack
description: How to build and run the srag-sentinel container stack — multi-stage Dockerfile with uv, Docker Compose (profiles, networks, healthchecks, secrets), SurrealDB service, OpenTelemetry Collector, Jaeger, Prometheus and Grafana provisioning. Use when editing Dockerfile, compose.yaml, observability/ or CI image jobs. Use the vendored `otel-python` skill for in-app instrumentation.
---

# srag-sentinel · Docker, Compose and the telemetry stack

Spec: `docs/specs/06-observability-deployment.md`.

## Rules
- Dockerfile: multi-stage (`builder` with uv → slim final), non-root user, read-only root fs with explicit volumes, `HEALTHCHECK`, no secrets in layers, `.dockerignore` excludes `.git`, `data/`, `.env`. Install uv deps with the lockfile (`uv sync --locked`/`--frozen`). Final stage adds only WeasyPrint's system libs.
- Compose: pinned image tags (never `latest`); networks `frontend`, `data` (`internal: true`), `telemetry`; one-shot jobs (`ingest`, `diagram`) under `profiles`; `depends_on` with `condition: service_healthy`; `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`.
- SurrealDB: persistent volume, no host port by default (a `dev` profile may publish it), root credentials only for bootstrap; the app uses role users created by `db init`.
- App exports OTLP **only to the Collector**. Collector config (`observability/otel-collector.yaml`): receivers OTLP; processors `memory_limiter`, `batch`, attribute redaction; exporters to Jaeger (OTLP) and Prometheus. Grafana datasources and dashboards are provisioned from files, not clicked together.
- Validate: `docker compose config` in CI, healthchecks green, one trace visible in Jaeger, dashboards populated after a run.
- OTel Python API/SDK details (providers, exporters, instrumentation, performance): see the vendored `otel-python` skill; LLM spans follow the GenAI semantic conventions (still evolving — pin and re-check) and must not capture prompt/response content.

## References (verified 2026-11-16)
- Compose — https://docs.docker.com/compose/ · profiles — https://docs.docker.com/compose/how-tos/profiles/
- Multi-stage builds — https://docs.docker.com/build/building/multi-stage/
- uv in Docker — https://docs.astral.sh/uv/guides/integration/docker/
- SurrealDB on Docker — https://surrealdb.com/docs/surrealdb/installation/running/docker
- OpenTelemetry Python — https://opentelemetry.io/docs/languages/python/
- OTel Collector — https://opentelemetry.io/docs/collector/
- GenAI semantic conventions — https://opentelemetry.io/docs/specs/semconv/gen-ai/
- Jaeger — https://www.jaegertracing.io/docs/ · Prometheus — https://prometheus.io/docs/introduction/overview/
- Grafana provisioning — https://grafana.com/docs/grafana/latest/administration/provisioning/
- GitHub Actions — https://docs.github.com/en/actions · Graphviz (diagram PDF) — https://graphviz.org/documentation/
