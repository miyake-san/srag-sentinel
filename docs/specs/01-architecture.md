# 01 — Arquitetura

Parte de [SPEC.md](../../SPEC.md).

## 1. Visão

Um **Agente Orquestrador** (LangGraph) coordena três ferramentas — `get_srag_metrics`, `get_srag_series` (banco) e `search_news` (notícias) — e dois passos de LLM (pesquisa de notícias e síntese). Tudo passa por camadas de guardrails e é registrado na trilha de auditoria e em traces OTel.

```
 Cliente (CLI / HTTP)
        │  POST /v1/reports {uf, as_of}
        ▼
 ┌─────────────────────────── API FastAPI ───────────────────────────┐
 │  valida entrada (G1) → run_id → inicia trace OTel + auditoria      │
 └───────────────────────────────┬───────────────────────────────────┘
                                 ▼
 ┌──────────────── Orquestrador (LangGraph StateGraph) ───────────────┐
 │ 1 validate_request ─► 2 fetch_metrics ─► 3 plan_news_research (LLM)│
 │                                              │                     │
 │                                              ▼                     │
 │ 6 verify_narrative ◄─ 5 synthesize (LLM) ◄─ 4 collect_news ─► G2   │
 │        │ (G3: grounding, PII, política)                            │
 │        ▼                                                           │
 │ 7 render_report ─► 8 finalize (auditoria selada)                   │
 └──────┬───────────────────────┬──────────────────────┬──────────────┘
        │ Tools                 │ LLM                  │ Tools
        ▼                       ▼                      ▼
  SurrealDB (db `data`,   Provedor LLM           NewsProvider
  agregados diários;      (Anthropic | Gemini |  (GNews RSS→GDELT→Tavily)
  usuário read-only)       NVIDIA NIM | OpenRouter) → domínios/URLs
        ▲
        │ ingestão (job): Open DATASUS (Parquet) → raw (staging) → agregação diária/UF
        │                 (allowlist, limpeza) → SurrealDB `data`

 Transversal: Guardrails (G1 entrada · G2 notícias · G3 saída · G4 orçamento)
              Governança (SurrealDB `audit`, hash chain) · SurrealDB `app` (relatórios, cache)
              OTel (traces/metrics/logs)
```

## 2. Princípios

1. **Números por código, texto por LLM.** Métricas são funções determinísticas e testáveis; o LLM só redige a partir de um payload estruturado.
2. **Grafo explícito, autonomia limitada.** O fluxo é fixo (auditável); o LLM decide apenas *o que pesquisar* (queries/seleção de notícias) e *como redigir*, dentro de orçamento e schema.
3. **Fail-closed.** Qualquer falha de guardrail na saída degrada para relatório só com métricas e gráficos (+ aviso), nunca para texto não verificado.
4. **Portas e adaptadores.** Domínio e agente dependem de protocolos (`MetricsRepository`, `NewsProvider`, `ChatModel`); trocar provedor não toca no grafo.
5. **Observável e auditável por construção.** Cada nó/tool emite span OTel *e* registro de auditoria (dois propósitos: operação vs. prestação de contas).

## 3. Componentes

| Componente | Responsabilidade | Local |
|---|---|---|
| Ingestor | baixa Parquet, valida schema, aplica allowlist e limpeza, **agrega por dia/UF** e faz upsert no SurrealDB `data` + manifest (hash, data, URL, linhas) | `data/` |
| Repositório de métricas | executa SurrealQL parametrizado (SDK async) com usuário **somente leitura** | `data/repository.py` |
| Esquema do banco | `.surql` versionados: tabelas, índices, usuários, permissões | `db/schema/` |
| Métricas de domínio | definições puras (ver [02](02-data-and-metrics.md)) | `domain/` |
| NewsProvider | busca, normaliza (título, fonte, data, URL, trecho), deduplica | `news/` |
| Agente | grafo, estado, nós, prompts | `agent/`, `llm/prompts/` |
| Guardrails | G1–G4 ([04](04-guardrails-security.md)) | `guardrails/` |
| Auditoria | registro append-only encadeado ([05](05-governance-audit.md)) | `governance/` |
| Relatório | gráficos SVG, HTML Jinja2 com autoescape, JSON | `reporting/` |
| Observabilidade | provider OTel, métricas customizadas | `observability/` |

## 4. Decisões de arquitetura (ADRs a registrar em `docs/adr/`)

| ADR | Decisão | Alternativas descartadas | Motivo |
|---|---|---|---|
| 0001 | **LangGraph StateGraph** com fluxo fixo e 2 nós LLM | agente ReAct livre; CrewAI/AutoGen | auditabilidade, previsibilidade de custo, guardrails por aresta, *checkpointing* |
| 0002 | **Sem text-to-SQL**; tools de métricas parametrizadas | LLM gera SQL | elimina injeção/vazamento; métricas reproduzíveis |
| 0003 | **SurrealDB** (server em container; bancos `data`, `audit`, `app`) com **agregados diários por UF** (sem linhas individuais) | DuckDB+Parquet; Postgres; pandas | escolha do usuário; multi-modelo (documentos + tabelas + índices) cobre dados, auditoria e cache num só motor; usuários/permissões por banco; agregados reduzem risco de reidentificação e tornam as consultas O(dias×UF) |
| 0004 | **Dois estágios de LLM com separação de privilégios**: o LLM que lê notícias não tem tools e só emite JSON estruturado | um único agente com tools + notícias no contexto | mitiga prompt injection indireta |
| 0005 | **Verificação de grounding determinística** (regex de números/URLs vs payload) | LLM-as-judge | verificável, barato, sem circularidade (judge opcional como sinal extra) |
| 0006 | **Auditoria hash-chained em JSONL**, separada da telemetria OTel | só logs/traces | tamper-evidence, retenção e acesso distintos |
| 0007 | **Fábrica de provedores explícita** (Anthropic default, Gemini, NVIDIA NIM, OpenRouter) sobre a interface `BaseChatModel` do LangChain + fake LLM em testes | `init_chat_model` com prefixo (nem todos os provedores resolvem por prefixo na doc); SDK de um provedor | portabilidade, testes offline, teste de conformidade único |
| 0008 | **Python 3.14 + uv** (3.15 avaliado e adiado) | 3.15 (sem wheels cp315 de `zstandard`/`pyyaml`); 3.12/3.13 + pip | versão mais recente com cobertura completa de wheels (T0a); ver [ADR 0008](../adr/0008-python-version.md) |
| 0009 | **OTel Collector como único destino da app** (OTLP) | exportar direto a cada backend | desacopla backends; igual a produção |
| 0010 | **Gráficos SVG estáticos (matplotlib)** | Plotly/JS | relatório autocontido, sem JS, CSP restritiva |
| 0011 | **Eixo temporal = `DT_NOTIFIC`** (não início de sintomas) | `DT_SIN_PRI` | evita falsa queda nos últimos dias por atraso de notificação (ver [02](02-data-and-metrics.md) §5) |

## 5. Fluxo de dados (execução de um relatório)

1. G1 valida `{uf, as_of, window_days}`; gera `run_id` (UUIDv7) e `trace_id`.
2. `fetch_metrics`: chama o repositório → `MetricsPayload` (4 métricas, 2 séries, metadados de maturidade/completude).
3. `plan_news_research` (LLM #1, sem tools): recebe **apenas** o payload agregado e propõe ≤ 3 queries (schema Pydantic); G2-pré valida.
4. `collect_news`: `search_news` executa as queries; G2 filtra (allowlist/score de domínio, idioma, janela de datas, deduplicação, sanitização anti-injeção, PII scrub) → ≤ N artigos.
5. `synthesize` (LLM #2, sem tools): recebe payload + artigos **delimitados como dado não confiável**; devolve `Narrative` (schema) com afirmações citando `metric_id`/`article_id`.
6. `verify_narrative` (G3): grounding numérico e de citações, política de conteúdo clínico, PII, tamanho. Falhou → 1 retry com feedback; falhou de novo → relatório degradado.
7. `render_report`: HTML + JSON + **PDF** (+ hashes de cada artefato; relatório persistido no banco `app`). 8. `finalize`: sela a auditoria (hash do relatório, `prev_hash`).

## 6. Atributos de qualidade (metas)

| Atributo | Meta |
|---|---|
| Latência | p95 ≤ 90 s fim a fim; métricas ≤ 2 s |
| Custo | ≤ 2 chamadas LLM por relatório (+1 retry); orçamento de tokens configurável |
| Disponibilidade da PoC | degrada sem notícias ou sem LLM; nunca 500 por dependência externa |
| Reprodutibilidade | mesmo `as_of` + mesmo `data_snapshot_sha256` (hash do conjunto de agregados) ⇒ mesmas métricas bit a bit |
| Segurança | ver [04](04-guardrails-security.md) |

## 7. Diagrama conceitual (entregável PDF)

Fonte versionada em `docs/architecture/architecture.dot` (Graphviz); PDF gerado por `docker compose run --rm diagram` e commitado. Deve mostrar: Orquestrador, Tools (`get_srag_metrics`, `get_srag_series`, `search_news`), LLM (2 estágios), banco (SurrealDB: `data`, `audit`, `app`) com ingestão do Open DATASUS (Parquet → agregados), fontes de notícias, guardrails, auditoria e pipeline OTel (Collector → Jaeger/Prometheus/Grafana).

## 8. Riscos

| Risco | Mitigação |
|---|---|
| Wheels ausentes em Python 3.15 (confirmado: `zstandard`, `pyyaml`) | **mitigado:** projeto em 3.14 (ADR 0008); reavaliar 3.15 quando houver wheels |
| SDK Python do SurrealDB 3.x vs. servidor 4.x | teste de integração contra o container na tarefa 0; fixar versão do servidor por tag |
| Append-only no SurrealDB depende de permissões de record access (usuários de sistema ignoram `PERMISSIONS` de tabela) | spike na tarefa 0; hash chain + `UNIQUE(seq)` + `READONLY` como defesa em profundidade; fallback em [05](05-governance-audit.md) |
| PDF (WeasyPrint) exige libs de sistema (Pango) na imagem | instalar no estágio final; teste de render no CI; fallback: PDF via outro renderizador com ADR |
| Provedores de LLM divergem em saída estruturada | teste de conformidade único por provedor (`live`) + validação Pydantic + retry |
| Portal Open DATASUS muda URLs (confirmado: API CKAN 404; nome do arquivo varia por semana) | descoberta pela página do recurso + regex restrita ao prefixo S3, `--url` override, teste com fixture HTML, falha explícita (ADR 0012) |
| GDELT limitado (1 req/5 s, 429 frequente, baixa relevância) e Google News RSS sem SLA/ToS de uso não comercial | cadeia de provedores (RSS → GDELT → Tavily), limitador, cache, filtro G2 obrigatório, degradação `NEWS_UNAVAILABLE`; ressalva de ToS no README |
| Atraso de notificação distorce "últimos dias" | avisos de maturidade no relatório (ver [02](02-data-and-metrics.md)) |
| Prompt injection via notícia | ADR 0004 + G2 + G3 |
