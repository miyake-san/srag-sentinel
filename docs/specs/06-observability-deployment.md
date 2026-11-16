# 06 — Observabilidade (OpenTelemetry) e Deployment

Parte de [SPEC.md](../../SPEC.md).

## 1. Topologia (Docker Compose, "produção em miniatura")

```
app (FastAPI) ──WS/HTTP──► surrealdb (db: data · audit · app; RocksDB/SurrealKV em volume)
ingest (job)  ──WS───────►      ▲ rede `data` (internal)
app (FastAPI) ──OTLP/gRPC──► otel-collector ──► jaeger      (traces)
ingest (job)  ──OTLP───────►        │     ├──► prometheus   (métricas, scrape do exporter do Collector)
                                    │     └──► logs → stdout/arquivo (debug) | Loki (opcional)
                                    └──► grafana (lê Prometheus + Jaeger)
volumes: surrealdb-data/ (banco), audit-export/ (JSONL), reports/ (artefatos), data/raw (staging do ingest, efêmero)
redes:   frontend (app) · data (app, ingest, surrealdb; internal) · telemetry (app, collector, backends)
```

| Serviço | Imagem (tag fixa; versões definidas na tarefa de infra) | Notas |
|---|---|---|
| `surrealdb` | `surrealdb/surrealdb` tag fixa (baseline **v4.0.1**, 2026-11-09), `start` com armazenamento persistente em volume | usuário root só no bootstrap (`db init` cria usuários por papel e depois a app não usa root); healthcheck `surreal isready`; **sem porta publicada** no perfil padrão (porta só em perfil `dev`) |
| `app` | build local `python:3.14-slim` multi-stage (+ libs de sistema do WeasyPrint) | não-root, read-only fs, healthcheck `/healthz` (inclui `readyz` → banco acessível e dados presentes) |
| `ingest` | mesma imagem, `command: srag-sentinel ingest`; `profiles: [jobs]` | executa sob demanda |
| `otel-collector` | `otel/opentelemetry-collector-contrib` | receivers OTLP; processors `memory_limiter`, `batch`, `attributes/redaction`; exporters Jaeger (OTLP), Prometheus |
| `jaeger` | `jaegertracing/jaeger` (v2) | UI em `:16686` |
| `prometheus` | `prom/prometheus` | scrape do Collector; regras de alerta de exemplo |
| `grafana` | `grafana/grafana` | datasources e dashboards **provisionados** em `observability/grafana/` |
| `diagram` | Graphviz | gera `architecture.pdf` |

Config em arquivos versionados (`observability/otel-collector.yaml`, `prometheus.yml`). Sem segredos no Compose: `env_file: .env` (ignorado pelo git) + `.env.example`.

## 2. Sinais OpenTelemetry

Setup em `observability/setup.py`; atributos de recurso: `service.name=srag-sentinel`, `service.version`, `deployment.environment`.

### Traces
- 1 trace por relatório; raiz `report.generate` (atributos: `run_id`, `scope.uf`, `status`).
- Span por nó do grafo (`node.<nome>`), por tool (`tool.<nome>`), por chamada LLM (`llm.<nome>`), por guardrail (`guardrail.<G#>`).
- Spans LLM seguem as **convenções semânticas GenAI** do OTel (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens/output_tokens`, `gen_ai.response.finish_reasons`) — convenções ainda em evolução: fixar versão e tratar como opt-in. **Conteúdo de prompts/respostas não é capturado** (ver [04](04-guardrails-security.md)).
- Propagação W3C `traceparent` da API → grafo; `run_id` também como atributo/baggage para correlação com a auditoria.

### Métricas
| Métrica | Tipo | Dimensões |
|---|---|---|
| `srag.report.duration` | histograma (s) | `status` |
| `srag.report.total` | contador | `status` (`ok/degraded/failed`) |
| `srag.node.duration` | histograma | `node` |
| `srag.llm.tokens` | contador | `direction`, `model` |
| `srag.llm.cost_usd` (estimado) | contador | `model` |
| `srag.tool.calls` / `srag.tool.errors` | contador | `tool` |
| `srag.guardrail.verdicts` | contador | `layer`, `rule`, `action` |
| `srag.news.articles` | histograma | `stage` (`retrieved/accepted`) |
| `srag.data.freshness_days` | gauge | — |

### Logs
JSON estruturado (stdlib `logging` + handler OTel), com `trace_id`/`span_id`/`run_id`; **sem PII e sem payloads**; níveis configuráveis.

### Dashboards e alertas (Grafana/Prometheus)
Painéis: volume e taxa de degradação, latência p50/p95 por nó, tokens/custo, vereditos de guardrail (bloqueios por regra), frescor dos dados. Alertas de exemplo: taxa de `degraded` > 20 % em 15 min; p95 > 90 s; `data.freshness_days` > 10.

## 3. Dockerfile (requisitos)

- Multi-stage: estágio `builder` com uv (`uv sync --frozen --no-dev`) → estágio final `python:3.14-slim` copiando apenas o venv e `src/`.
- `USER` não-root (uid fixo), `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `HEALTHCHECK`.
- Sem segredos em camadas; `.dockerignore` exclui `.git`, `data/`, `.env`, `tests/` (exceto estágio de teste).
- Estágio `test` separado para rodar a suíte no CI dentro do container.
- Imagens `python:3.14-slim` e `python:3.15-slim` existem (T0a); usamos 3.14 por falta de wheels cp315 (ADR 0008).
- Estágio final instala somente as libs de sistema exigidas pelo WeasyPrint — **validado no T0d** em `python:3.14-slim`: `libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core` (com `apt-get install --no-install-recommends` e limpeza de `/var/lib/apt/lists`) e `build arg LLM_EXTRAS` (`anthropic` por padrão; `google`, `nvidia`, `openrouter` opcionais).
- O cliente SurrealDB roda em modo **servidor remoto** (WebSocket); o modo embarcado do SDK não é usado (evita dependência de wheel nativo).

## 4. Configuração

`pydantic-settings`, prefixo `SRAG_`, validada no boot (falha rápida); `.env.example` lista: `SRAG_LLM_PROVIDER` (`anthropic`|`google_genai`|`nvidia`|`openrouter`), `SRAG_LLM_MODEL`, `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` / `NVIDIA_API_KEY` (+ `SRAG_NVIDIA_BASE_URL`) / `OPENROUTER_API_KEY` (apenas a do provedor ativo), `SRAG_SURREAL_URL`, `SRAG_SURREAL_NS`, usuários/senhas por papel (`SRAG_SURREAL_INGEST_*`, `SRAG_SURREAL_API_RO_*`, `SRAG_SURREAL_AUDIT_*`) e `SURREAL_ROOT_*` (só bootstrap), `SRAG_NEWS_PROVIDER`, `TAVILY_API_KEY` (opcional), `SRAG_AUDIT_STORE_CONTENT=false`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, limites de orçamento. Chaves de API como `SecretStr`.

## 5. CI (GitHub Actions)

Jobs: `lint` (ruff) · `types` (mypy) · `test` (pytest + cobertura ≥ 85 %) · `security` (gitleaks, pip-audit, Trivy na imagem) · `build` (imagem) · `e2e` (compose com SurrealDB real, LLM/notícias fake + verificação de trace no Jaeger, PDF gerado/abrível e `audit verify`) · `llm-conformance` (manual/noturno, `live`, uma execução por provedor com segredo disponível) · `diagram` (regenera PDF e falha se divergir do commitado). Cache do uv; Python 3.14 via `setup-uv`.

## 6. Caminho para produção (documentar no README, não implementar)

Kubernetes + OTel Operator, Collector em DaemonSet/gateway, backends gerenciados (Tempo/Mimir/Loki ou vendor), segredos via Vault/Secret Manager, SurrealDB em cluster (TiKV) ou SurrealDB Cloud, auditoria arquivada em object-lock (WORM), ingestão agendada (Airflow/CronJob), cache de notícias em Redis, autenticação OIDC, políticas de rede e rate limit no gateway.

## 7. Aceitação

- [ ] `docker compose up --build` sobe todos os serviços (incluindo SurrealDB) *healthy* num clone limpo; `db init` e `ingest` rodam sem intervenção manual além do `.env`.
- [ ] Um relatório gera 1 trace completo no Jaeger com spans de nós/tools/LLM/guardrails.
- [ ] Dashboards Grafana provisionados exibem as métricas da §2 após uma execução.
- [ ] Nenhum atributo de span/log contém payloads ou PII (teste automatizado sobre saída do Collector em modo debug).
- [ ] `docker compose down -v` + `up` é reprodutível; imagem roda como não-root com fs somente leitura.
