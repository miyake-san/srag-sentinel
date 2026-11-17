#!/usr/bin/env bash
# End-to-end smoke test of the Compose stack: database, schema, real OpenDATASUS ingestion, one report
# (HTML, JSON, PDF) and an audit-chain verification. Needs Docker and a filled .env (see env.example).
# Without a valid model key the report is still produced, but degraded (narrative omitted).
set -euo pipefail

PROJECT="${E2E_PROJECT:-srag-e2e}"
compose() { docker compose -p "$PROJECT" "$@"; }
trap 'compose down -v >/dev/null 2>&1 || true' EXIT

compose up -d --build surrealdb otel-collector jaeger prometheus grafana
compose --profile jobs run --rm init
compose --profile jobs run --rm ingest
compose up -d --build app

out="$(compose run --rm --no-deps app report --uf "${E2E_UF:-BR}")"
echo "$out"
run_id="$(grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' <<<"$out" | head -1)"
test -n "$run_id" || { echo "no run id in the output"; exit 1; }
for artifact in report.html report.json report.pdf; do
  compose run --rm --no-deps --entrypoint test app -s "/data/reports/$run_id/$artifact" \
    || { echo "missing $artifact"; exit 1; }
done
compose run --rm --no-deps app audit verify
echo "e2e ok: run $run_id"
