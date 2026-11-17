# Visão arquitetural: componente por componente

Cada parte do sistema, onde está no código, por que existe e onde estão a especificação, o ADR e os testes. Diagramas Mermaid em [`architecture/architecture.md`](architecture/architecture.md) e em PDF: [`architecture/architecture.pdf`](architecture/architecture.pdf). Índice das decisões: [`adr/`](adr/).

> Contexto fictício: a "HealthCare Co." não existe; os dados de saúde são reais e públicos.

## Mapa geral

```mermaid
flowchart TB
    cli["cli.py · api/"] --> svc["service.py<br/>raiz de composição"]
    svc --> graph["agent/graph.py<br/>LangGraph fixo"]
    graph --> tools["agent/tools · data/ · domain/"]
    graph --> news["news/"]
    graph --> g["guardrails/ G1 G2 G3 G4"]
    graph --> kg["kg/ GraphRAG"]
    graph --> llm["llm/ router · juiz · provedores"]
    graph --> rep["reporting/"]
    graph --> gov["governance/ auditoria"]
    svc --> obs["observability/"]
    tools & kg & gov --> db[("db/ SurrealDB")]
```

## Componentes

| Parte | Código | Responsabilidade | Decisões e specs | Testes |
|---|---|---|---|---|
| **Composição e serviço** | [`service.py`](../src/srag_sentinel/service.py) | abre cada conexão com o usuário de menor privilégio, monta modelos/notícias/KG e roda um relatório; guarda os artefatos | [spec 01](specs/01-architecture.md), [ADR 0003](adr/0003-surrealdb-single-store.md) | `tests/integration/test_service.py` |
| **API** | [`api/`](../src/srag_sentinel/api) | rotas FastAPI, erros RFC 9457 sem eco da entrada, `healthz`/`readyz` | [spec 03 §6](specs/03-agent-and-tools.md) | `tests/unit/api/` |
| **CLI** | [`cli.py`](../src/srag_sentinel/cli.py) | `db init`, `ingest`, `metrics`, `report`, `serve`, `audit`, `kg prune` | [guia de uso](usage-guide.md) | `tests/unit/test_cli_commands.py` |
| **Configuração** | [`settings.py`](../src/srag_sentinel/settings.py) | variáveis `SRAG_*`, segredos como `SecretStr`, validação no boot | [ADR 0007](adr/0007-llm-port-and-providers.md) | `tests/unit/llm/test_factory.py` |
| **Ingestão** | [`data/ingest/`](../src/srag_sentinel/data/ingest) | lê só 7 colunas do Parquet remoto, agrega por dia e UF, guarda manifesto e hash | [ADR 0002](adr/0002-datasus-column-allowlist-and-aggregates.md), [0012](adr/0012-datasus-findings.md), [0015](adr/0015-settle-days-and-partial-ingest-guard.md), [spec 02](specs/02-data-and-metrics.md) | `tests/unit/ingest/`, `tests/integration/test_ingest.py` |
| **Domínio** | [`domain/`](../src/srag_sentinel/domain) | janelas, métricas M1–M4 (com numerador, denominador, completude) e séries | [ADR 0011](adr/0011-notification-date-and-proxy-metrics.md), [spec 02 §6](specs/02-data-and-metrics.md) | `tests/unit/domain/` |
| **Banco** | [`db/`](../src/srag_sentinel/db) | cliente, `db init` idempotente, esquemas `.surql`; bancos `data`, `app`, `audit`, `kg` | [ADR 0003](adr/0003-surrealdb-single-store.md), [0013](adr/0013-surrealdb-findings.md) | `tests/integration/` |
| **Agente (LangGraph)** | [`agent/`](../src/srag_sentinel/agent) | fluxo fixo com um retry, estado serializável, nós auditados, prompts versionados | [ADR 0001](adr/0001-langgraph-fixed-flow.md), [spec 03](specs/03-agent-and-tools.md) | `tests/integration/test_graph.py` |
| **Notícias** | [`news/`](../src/srag_sentinel/news) | Google News RSS → GDELT em cadeia, deduplicação, cache em memória | [ADR 0006](adr/0006-news-provider-chain.md), [0014](adr/0014-news-and-pdf-findings.md) | `tests/unit/news/` |
| **Guardrails** | [`guardrails/`](../src/srag_sentinel/guardrails) | G1 entrada, G2 notícias (injeção, PII, confiança), G3 narrativa (números e referências), G4 orçamento | [ADR 0004](adr/0004-llms-without-tools-untrusted-data.md), [spec 04](specs/04-guardrails-security.md) | `tests/guardrails/` (inclui o corpus adversarial) |
| **LLM: porta e provedores** | [`llm/factory.py`](../src/srag_sentinel/llm/factory.py), [`fallback.py`](../src/srag_sentinel/llm/fallback.py) | porta mínima `StructuredModel`; OpenRouter, Groq, NVIDIA NIM, Unsloth, Gemini, Ollama e Anthropic; failover por prioridade | [ADR 0007](adr/0007-llm-port-and-providers.md), [conformidade](provider-conformance.md) | `tests/unit/llm/` |
| **LLM: router e juiz** | [`llm/router/`](../src/srag_sentinel/llm/router) | política estática tarefa → camadas (small → large), validadores antes do juiz, rubricas versionadas, calibração (κ) | [ADR 0018](adr/0018-llm-router-and-judge.md), [spec 08](specs/08-llm-router-judge.md) | `tests/unit/llm/test_judge.py`, `tests/live/` |
| **GraphRAG e grafo** | [`kg/`](../src/srag_sentinel/kg) | ontologia fechada, extração de afirmações com proveniência, quarentena, recuperação BM25 + vizinhança, resumos regionais | [ADR 0016](adr/0016-graphrag-on-surrealdb.md), [0017](adr/0017-knowledge-graph-model.md), [0019](adr/0019-surrealdb-kg-findings.md), [spec 07](specs/07-graphrag-knowledge-graph.md) | `tests/unit/kg/`, `tests/integration/test_kg_*` |
| **Governança** | [`governance/`](../src/srag_sentinel/governance) | cadeia de hashes só de acréscimo, `verify`/`export`, âncora externa | [ADR 0005](adr/0005-hash-chained-audit.md), [spec 05](specs/05-governance-audit.md) | `tests/integration/test_audit.py` |
| **Relatório** | [`reporting/`](../src/srag_sentinel/reporting) | gráficos SVG, HTML autocontido, JSON versionado, PDF do mesmo HTML | [ADR 0009](adr/0009-report-formats.md) | `tests/unit/reporting/` |
| **Observabilidade** | [`observability/`](../src/srag_sentinel/observability), [`observability/`](../observability) | spans e métricas `srag.*` alimentados pela auditoria; Collector, Jaeger, Prometheus, Grafana | [ADR 0010](adr/0010-telemetry-from-audit-events.md), [spec 06](specs/06-observability-deployment.md) | `tests/integration/test_otel_graph.py` |
| **Deploy** | [`Dockerfile`](../Dockerfile), [`compose.yaml`](../compose.yaml), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | imagem não-root e somente leitura, redes separadas, CI | [spec 06 §1,3,5](specs/06-observability-deployment.md), [ADR 0008](adr/0008-python-version.md) | `scripts/e2e.sh` |

## Fluxo de um relatório

1. **G1** valida a requisição (esquema estrito; os valores nunca voltam na resposta).
2. **Métricas e séries** vêm do banco `data` por código determinístico, lidas com um usuário só de leitura.
3. O modelo pequeno **planeja** as buscas (com plano padrão se falhar) e as **notícias** são coletadas.
4. **G2** sanitiza, filtra, remove PII e entrega o texto **escapado e delimitado**.
5. O **grafo** é construído (entidades por dicionário, afirmações por modelo pequeno + validadores + juiz; reprovados em quarentena) e o **GraphRAG** recupera evidências com caminho e proveniência.
6. O modelo grande **sintetiza** a narrativa; o **G3** confere cada número e referência. Uma segunda tentativa recebe o feedback; se falhar de novo, o relatório sai **sem texto**.
7. **Render** (HTML, JSON, PDF) e **finalização**; todo passo grava na **auditoria** e emite telemetria sem conteúdo.

## Onde cada requisito do desafio está atendido

| Critério | Onde |
|---|---|
| Escolha da arquitetura | este documento, [ADRs](adr/), [diagramas](architecture/architecture.md) |
| Governança e transparência | auditoria encadeada ([ADR 0005](adr/0005-hash-chained-audit.md)), proveniência no grafo, relatório com proxies e limitações |
| Guardrails | G1–G4 ([ADR 0004](adr/0004-llms-without-tools-untrusted-data.md)), [corpus adversarial](../tests/guardrails/corpus/injection.txt) |
| Dados sensíveis | só 7 colunas e só agregados ([ADR 0002](adr/0002-datasus-column-allowlist-and-aggregates.md)), scrubber de PII, segredos por ambiente |
| Código limpo | ruff, mypy strict, 699 testes (96% de cobertura), [skills do projeto](../.claude/skills/README.md) |

Outros documentos: [guia de uso](usage-guide.md) · [avaliação](evaluation.md) · [impacto](impact.md) · [conformidade dos provedores](provider-conformance.md) · [CHANGELOG](../CHANGELOG.md) · [plano e tarefas](../tasks/).
