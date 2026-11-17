# Guia de uso

Exemplos práticos do SRAG Sentinel, do zero ao relatório. Para a visão geral veja o [README](../README.md); para os componentes, a [visão arquitetural](architecture-overview.md).

> A empresa de contexto (HealthCare Co.) é **fictícia**; os dados do OpenDATASUS são reais e públicos.

## 1. Preparar o ambiente

### Com Docker (recomendado)
```bash
cp env.example .env                                  # preencha senhas e provedores (ver §2)
docker compose --profile jobs run --rm init          # bancos, esquema e usuários por papel
docker compose --profile jobs run --rm ingest        # baixa e agrega o OpenDATASUS
docker compose up -d --build                         # SurrealDB, API e telemetria
```

### Local (desenvolvimento)
```bash
uv sync --all-extras
export SURREAL_ROOT_PASSWORD=<senha-descartavel>
docker compose -f compose.yaml -f compose.dev.yaml up -d surrealdb   # publica só em 127.0.0.1
# as demais senhas (SRAG_SURREAL_*_PASSWORD) vêm do ambiente; veja env.example
uv run srag-sentinel db init
uv run srag-sentinel ingest
```

## 2. Escolher o(s) provedor(es) de LLM

Nenhum provedor é obrigatório para ver métricas e gráficos; sem modelo utilizável o relatório sai **degradado** (sem narrativa). Informe só os que você usa, **chaves sempre por variável de ambiente** (nunca em arquivo versionado nem em conversa).

```bash
# Failover por prioridade: o primeiro utilizável atende; se falhar, tenta o próximo
export SRAG_LLM_PRIORITY="openrouter=<modelo>,groq=<modelo>,nvidia=<modelo>,unsloth=<modelo>,google_genai=<modelo>,ollama=<modelo>"
export OPENROUTER_API_KEY=...        # defina apenas as chaves que tiver
export GROQ_API_KEY=...
export SRAG_UNSLOTH_BASE_URL=http://localhost:8888/v1     # servidor compatível com a API da OpenAI
export SRAG_OLLAMA_BASE_URL=http://localhost:11434        # padrão
```

Só Groq:
```bash
export GROQ_API_KEY=...
export SRAG_LLM_PRIORITY="groq=<modelo>"
```
Só local (sem chave): `SRAG_LLM_PRIORITY="ollama=<modelo>"` com `ollama serve` rodando. Se um servidor não aceitar a saída estruturada padrão: `SRAG_LLM_STRUCTURED_METHOD=function_calling` (ou `json_mode`).

Camadas opcionais: `SRAG_ROUTER_SMALL_PROVIDER`/`SRAG_ROUTER_SMALL_MODEL` (modelo pequeno para extração do grafo) e `SRAG_ROUTER_JUDGE_PROVIDER`/`SRAG_ROUTER_JUDGE_MODEL` (juiz). Sem elas, tudo roda no modelo grande. Detalhes: [ADR 0007](adr/0007-llm-port-and-providers.md), [ADR 0018](adr/0018-llm-router-and-judge.md), [conformidade](provider-conformance.md).

## 3. Gerar relatórios

### CLI
```bash
uv run srag-sentinel report --uf BR                              # Brasil, janela de 30 dias
uv run srag-sentinel report --uf SP --window-days 14             # só São Paulo, 14 dias
uv run srag-sentinel report --uf RJ --as-of 2026-11-01           # data de referência fixa
```
Saída:
```text
run 27781898-d776-4118-b71b-14ff1bc731d1: degraded
  html: reports/27781898-.../report.html
  json: reports/27781898-.../report.json
  pdf:  reports/27781898-.../report.pdf
```
`ok` = relatório completo; `degraded` = saiu com avisos (veja `degradations` no JSON). No Docker: `docker compose run --rm --no-deps app report --uf BR`.

### API
```bash
uv run srag-sentinel serve --port 8080        # ou: docker compose up -d
```
Toda rota, exceto `/healthz` e `/readyz`, exige `Authorization: Bearer <chave>` com uma das chaves de `SRAG_API_KEYS` (separadas por vírgula; obrigatória fora de `SRAG_ENVIRONMENT=dev`, e o Compose roda em `prod`). Limites por padrão: 10 gerações por minuto por chave (429 com `Retry-After`), 2 gerações simultâneas (429), corpo de até 1 KiB e `Content-Type: application/json` (413/415). Veja [spec 09](specs/09-agent-and-api-security.md) e o [ADR 0020](adr/0020-api-perimeter-controls.md).
```bash
export SRAG_KEY=<sua-chave>          # a mesma de SRAG_API_KEYS
curl -s -X POST http://127.0.0.1:8080/v1/reports -H "Authorization: Bearer $SRAG_KEY" \
  -H 'content-type: application/json' -d '{"uf": "SP", "window_days": 30}'
```
```json
{
  "run_id": "27781898-d776-4118-b71b-14ff1bc731d1",
  "status": "ok",
  "degradations": [],
  "links": {
    "html": "/v1/reports/27781898-d776-4118-b71b-14ff1bc731d1?format=html",
    "json": "/v1/reports/27781898-d776-4118-b71b-14ff1bc731d1?format=json",
    "pdf":  "/v1/reports/27781898-d776-4118-b71b-14ff1bc731d1?format=pdf"
  }
}
```
```bash
curl -s -H "Authorization: Bearer $SRAG_KEY" "http://127.0.0.1:8080/v1/reports/<run_id>?format=pdf" -o relatorio.pdf
curl -s  http://127.0.0.1:8080/readyz          # {"status": "ready"} quando há banco e dados
```

Requisição inválida (nenhum valor é repetido na resposta):
```bash
curl -s -X POST http://127.0.0.1:8080/v1/reports -H "Authorization: Bearer $SRAG_KEY" \
  -H 'content-type: application/json' -d '{"uf": "BR; REMOVE TABLE x", "window_days": 500}'
```
```json
{"type": "about:blank", "title": "Invalid request", "status": 422,
 "detail": "The request body did not pass validation.",
 "errors": [{"field": "uf", "rule": "string_pattern_mismatch"}, {"field": "window_days", "rule": "less_than_equal"}]}
```

## 4. Ler um relatório

O `report.json` (`schema_version` 1.0) traz tudo que está no HTML:

| Campo | O que é |
|---|---|
| `report.status` / `degradations` | `ok` ou `degraded` e os códigos (`NARRATIVE_REJECTED`, `NEWS_UNAVAILABLE`, `KG_UNAVAILABLE`, `PLAN_FALLBACK`, `PDF_UNAVAILABLE`) |
| `report.metrics.metrics[]` | M1–M4 com `value`, `numerator`, `denominator`, `completeness`, `is_proxy` e `caveats` |
| `report.series` | série diária (30 dias, com média móvel) e mensal (12 meses, mês corrente parcial) |
| `report.narrative` | resumo e comentários **verificados** (ou `null` se o G3 rejeitou) |
| `report.articles` / `report.evidence` | fontes citadas; evidências do grafo com `graph_path` e proveniência |
| `report.models` / `report.prompts` | modelos e prompts (`id@versão`) usados |
| `artifacts` | SHA-256 do HTML e do PDF |

Exemplo com `jq`: `jq '.report.metrics.metrics[] | {metric_id, value, is_proxy}' report.json`.

## 5. Auditar uma execução

```bash
curl -s -H "Authorization: Bearer $SRAG_KEY" http://127.0.0.1:8080/v1/audit/<run_id>   # eventos (só contadores nos detalhes)
uv run srag-sentinel audit verify                                  # recalcula a cadeia de hashes
uv run srag-sentinel audit export --out audit.jsonl                # imprime o head: guarde-o fora do banco
uv run srag-sentinel audit verify --expected-head <hash-guardado>  # detecta truncamento do fim
```
Veja [ADR 0005](adr/0005-hash-chained-audit.md) e a [spec 05](specs/05-governance-audit.md).

## 6. Manutenção

```bash
uv run srag-sentinel ingest --years 2025 2026        # reingestão (idempotente)
uv run srag-sentinel metrics --uf SP --window-days 30  # só métricas e séries no terminal
uv run srag-sentinel kg prune                        # remove afirmações e artigos expirados do grafo
```

## 7. Observabilidade local
Com o Compose no ar: traces em Jaeger (`http://127.0.0.1:16686`), painéis em Grafana (`http://127.0.0.1:3000`, usuário `admin`). Ver [ADR 0010](adr/0010-telemetry-from-audit-events.md).

## 8. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `/readyz` devolve 503 | banco vazio ou inacessível | rode `init` e `ingest` |
| relatório `degraded` com `NARRATIVE_REJECTED` | modelo indisponível ou texto reprovado pelo G3 | confira provedores/chaves; veja o JSON e a auditoria |
| `no provider in the priority list is usable` | nenhum provedor da lista tem chave, endpoint ou pacote | exporte as chaves; instale extras (`--extra groq` etc.) |
| `PDF_UNAVAILABLE` | faltam bibliotecas do Pango | use a imagem Docker (já inclui) |
| `ingest` recusa um só arquivo anual | proteção contra contagens parciais (ADR 0015) | informe os dois anos ou use `--allow-partial` conscientemente |
| 401 / 429 / 413 / 415 | chave ausente ou errada / limite de taxa ou de concorrência / corpo grande / não é JSON | envie `Authorization: Bearer`, respeite `Retry-After`, veja o [perímetro](specs/09-agent-and-api-security.md) |
| 422 em `POST /v1/reports` | `uf`, `window_days` ou `as_of` inválidos | veja `errors[]` na resposta |
