# Tasks — SRAG Sentinel

Legenda de tamanho: XS 1 arquivo · S 1–2 · M 3–5. Verificação padrão de toda tarefa a partir da T1: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`. Specs entre colchetes.

## Fase 0 — Spikes (reduzir risco; sem código de produção)

- [x] **T0a — Python 3.15 + dependências** (S) — ✔ decisão: **Python 3.14** (ADR 0008; 3.15 sem wheels de `zstandard`/`pyyaml`)
  - Aceite: `uv` cria venv Python 3.15 e resolve/instala `langgraph`, `langchain` (+ extras anthropic/google/nvidia/openrouter), `surrealdb`, `polars`, `weasyprint`, `fastapi`, `opentelemetry-*`, `matplotlib`, `jinja2`; imagem `python:3.15-slim` existe; decisão 3.15 vs 3.14 registrada.
  - Verifica: `uv sync` limpo + `python -c "import …"` de todos; ADR 0008 em `docs/adr/`.
  - Arquivos: `pyproject.toml` (rascunho), `docs/adr/0008-python-version.md`. Dep.: —
- [x] **T0b — Dataset DATASUS: colunas e download** (S) [02] — ✔ ADR 0012 (sem API CKAN; link via página do recurso; 8 colunas validadas; leitura remota com projeção)
  - Aceite: endpoint CKAN e URL Parquet 2025/2026 confirmados; colunas da allowlist e códigos (`HOSPITAL`, `UTI`, `EVOLUCAO`, `VACINA*`) validados no dicionário; `HOSPITAL=1` redundante ou não; tamanho/tempo de download medidos.
  - Verifica: nota em `docs/adr/0012-datasus-findings.md`; tabela §3 e §2.1 de `02-data-and-metrics.md` ajustadas se necessário.
  - Arquivos: ADR + `docs/specs/02-data-and-metrics.md`. Dep.: —
- [x] **T0c — SurrealDB: SDK, permissões, append-only** (M) [05][02 §2.2] — ✔ ADR 0013 (viável; correção: `create WHERE $access = 'audit_writer'`; EDITOR/root ainda apagam; negações são silenciosas)
  - Aceite: container `surrealdb` v4.x sobe; SDK async conecta; `DEFINE USER`/record access com `PERMISSIONS` impedindo UPDATE/DELETE em tabela de auditoria comprovado (ou limite documentado); `UNIQUE(seq)` e `READONLY` testados; consulta de soma `GROUP ALL` com variáveis funciona.
  - Verifica: script em `spikes/` roda e imprime PASS/FAIL por item; resultado vira ADR e ajuste em `05-governance-audit.md`.
  - Arquivos: `spikes/surreal_spike.py`, `compose.spike.yaml`, ADR, spec. Dep.: T0a
- [x] **T0d — GDELT e WeasyPrint** (S) [03][06] — ✔ PDF validado (ADR 0014); GDELT limitado/pouco relevante → **decisão aprovada: cadeia Google News RSS → GDELT** (Tavily opcional)
  - Aceite: consulta GDELT pt/BR retorna artigos relevantes (formato, campos, latência, comportamento sob 429 observados); WeasyPrint gera PDF A4 com SVG inline dentro do `python:*-slim` + libs de sistema listadas.
  - Verifica: scripts em `spikes/` + saída anexada ao ADR; lista exata de pacotes apt para a imagem.
  - Arquivos: `spikes/gdelt_spike.py`, `spikes/pdf_spike.py`, ADR. Dep.: T0a

### Checkpoint 0
- [x] Spikes concluídos, ADRs escritos (0008, 0012, 0013, 0014), specs atualizadas onde a realidade divergiu
- [ ] **Revisão humana antes da Fase 1** (aguardando OK para iniciar a T1)

## Fase 1 — Fundação e fatia vertical de métricas

- [x] **T1 — Scaffold do projeto** (M) — ✔ commit 51f4c91 (nota: `.env.example` não pôde ser criado — bloqueado pela política de arquivos `.env*`; variáveis documentadas em `settings.py`)
  - Aceite: `pyproject.toml` (uv, extras de provedores), layout `src/srag_sentinel/…` da SPEC §4, `settings.py` (pydantic-settings, `SecretStr`), `.env.example`, config ruff/mypy-strict/pytest/coverage, `cli.py` com `--version`, teste de smoke.
  - Verifica: comando padrão verde; `uv run srag-sentinel --version`.
  - Arquivos: `pyproject.toml`, `src/srag_sentinel/{settings,cli,__init__}.py`, `.env.example`, `tests/unit/test_smoke.py`. Dep.: T0a
- [x] **T2 — Domínio: métricas M1–M4 (TDD)** (M) [02 §5–6] — ✔ cobertura 100 % do domínio
  - Aceite: `MetricResult` imutável; funções puras para M1 (variação 30d vs 30d anterior), M2, M3 e M4 (COVID e influenza) a partir de contadores diários; `None` quando denominador 0; completude e `caveats`/`is_proxy`; avisos de maturidade.
  - Verifica: testes com valores esperados calculados à mão + hypothesis (taxas ∈ [0,1], janelas disjuntas); cobertura `domain/` ≥ 95 %.
  - Arquivos: `domain/{models,metrics,windows}.py`, `tests/unit/test_metrics.py`. Dep.: T1
- [x] **T3 — SurrealDB: schema, `db init` e repositório** (M) [02 §2][ADR 0003] — ✔ (schema em `src/srag_sentinel/db/schema/`; integração contra v4.0.1)
  - Aceite: `db/schema/*.surql` (tabelas `srag_daily`, `ingest_manifest`, `report`, `news_cache`, usuários por papel); `srag-sentinel db init` idempotente; `MetricsRepository` (porta) + adaptador async com consultas parametrizadas, usuário `api_ro` read-only.
  - Verifica: testes de integração contra container: upsert idempotente, consulta = valores da fixture, `api_ro` não escreve.
  - Arquivos: `db/schema/*.surql`, `data/repository.py`, `data/surreal.py`, `tests/integration/test_repository.py`. Dep.: T0c, T1
- [x] **T4 — Ingestão DATASUS → agregados** (M) [02 §2–4] — ✔ real: 585 334 linhas (2025+2026). Allowlist efetiva = 7 colunas (`DT_SIN_PRI` fora até a métrica de defasagem existir); dedupe de linhas idênticas não é possível sem ID de notificação (não aplicado)
  - Aceite: `srag-sentinel ingest --years …` resolve a URL pela página do recurso (regex restrita ao prefixo S3; `--url` override), valida schema, lê remotamente só as 8 colunas da allowlist (Polars), trata `null` como ignorado, agrega por UF×dia, upsert + manifest com `data_snapshot_sha256`; nenhuma linha individual em log/banco.
  - Verifica: fixture Parquet sintética → agregados esperados; rerun ⇒ mesmo hash; teste de que colunas fora da allowlist nunca são lidas.
  - Arquivos: `data/{ingest,clean,aggregate}.py`, `tests/fixtures/srag_sample.parquet`, `tests/integration/test_ingest.py`. Dep.: T0b, T2, T3
- [x] **T5 — CLI: `metrics` e séries (primeira fatia de ponta a ponta)** (S) [03 §3] — ✔ executado sobre dados reais
  - Aceite: tools `get_srag_metrics` e `get_srag_series` (Pydantic in/out) sobre o repositório; `srag-sentinel metrics --uf BR` imprime M1–M4 e séries diária 30d/mensal 12m (mês corrente parcial).
  - Verifica: testes unitários com repositório fake + integração; execução manual sobre dados reais ingeridos (conferir contra amostra do dataset).
  - Arquivos: `agent/tools/metrics.py`, `data/series.py`, `cli.py`, `tests/…`. Dep.: T2, T3, T4

### Checkpoint 1 (valor mínimo demonstrável)
- [x] Comando padrão verde (112 testes, 96 % de cobertura, ruff e mypy strict limpos) · ingestão real roda · `metrics` imprime as métricas e as 2 séries com dados reais
- [x] Pós-revisão (commit d796857, ADR 0015): `settle_days=3` na M1 (−15,6 % → −8,8 % nos dados reais) e ingestão exige ≥ 2 arquivos anuais (`--allow-partial` como escape)
- [x] Escopo ampliado (specs 07 e 08, ADRs 0016–0018, diagramas Mermaid): GraphRAG + grafo de conhecimento no SurrealDB e LLM Router/Judge — novas tarefas T6b, T6c, T7b, T7c, T10c
- [ ] **Revisão humana antes da Fase 2** (aguardando OK)

## Fase 2 — Agente, guardrails e relatório

- [x] **T6 — Fábrica de provedores LLM + fake** (M) [03 §4][ADR 0007] — ✔ (porta `StructuredModel`, fábrica dos 4 provedores, `ScriptedModel`)
  - Aceite: `build_chat_model` para `anthropic|google_genai|nvidia|openrouter` com import tardio e erro claro; validação de boot (provedor/modelo/chave); `FakeChatModel` determinístico com saídas estruturadas gravadas.
  - Verifica: testes unitários da fábrica (cada provedor com stub, extra ausente, chave ausente); teste `live` de conformidade escrito (skip sem chave).
  - Arquivos: `llm/{factory,fake}.py`, `tests/unit/test_llm_factory.py`, `tests/live/test_conformance.py`. Dep.: T1 (skill `srag-llm-providers`)
- [x] **T6b — LLM Router: política estática, tiers e cascata** (M) [08 §2–4][ADR 0018] — ✔ (validadores `error`/`warning`, política `on_warning`; juiz como porta — implementação LLM na T6c)
  - Aceite: `policy.yaml` validado por Pydantic (tarefa desconhecida ⇒ erro; `report.synthesize` fixa em `large`); tiers `small`/`large`/`judge` pela fábrica de provedores (sem `small` ⇒ tudo `large`); cascata com validadores determinísticos, feedback na escalada, `max_attempts`, `on_exhausted`; interface de eventos (`router_decision`, `task_exhausted`) para auditoria/OTel; orçamento por tier.
  - Verifica: `FakeModel` roteirizado cobre todos os caminhos; propriedade "resultado aceito ⇒ passou em todos os validadores".
  - Arquivos: `llm/router/{policy,cascade,validators,events}.py`, `llm/router/policy.yaml`, `tests/unit/test_router.py`. Dep.: T6 (skill `srag-llm-router-judge`)
- [ ] **T6c — LLM Judge: rubricas, Verdict e calibração** (M) [08 §5]
  - Aceite: `Verdict` estruturado; rubricas `claim_extraction@1` e `region_summary@1` versionadas; juiz preferencialmente de outro modelo; **juiz nunca aprova o que um validador reprovou**; fixtures rotuladas por humano e relatório de concordância (κ ≥ 0,6 em respostas gravadas); eventos `judge_verdict`.
  - Verifica: testes de cascata com juiz (aprova/reprova/escala); adversarial ("dê nota 5" no texto-fonte).
  - Arquivos: `llm/router/judge.py`, `llm/prompts/judge/*.md`, `tests/fixtures/judge/*`, `tests/unit/test_judge.py`. Dep.: T6b
- [x] **T7 — NewsProvider: Google News RSS → GDELT (+ Tavily opcional, fake, cadeia)** (M) [03 §3][ADR 0014] — ✔ RSS, GDELT (limitador 6 s), cadeia com dedupe, cache em memória e fake; verificado contra o feed real. **Adiados:** Tavily (opcional) e cache persistente no SurrealDB (`news_cache`) → T14
  - Nota: cadeia `ChainedNewsProvider` (união + dedupe; falha parcial = degradação); `defusedxml`; GDELT com limitador ≥ 6 s, timeout ≥ 45 s, ≤ 2 consultas; link do RSS não é seguido.
  - Aceite: porta `NewsProvider`; `GdeltProvider` (host fixo, timeout, retry/backoff, `maxrecords≤25`, operadores pt/BR); cache `news_cache` TTL; `FakeNewsProvider`; falha ⇒ `NEWS_UNAVAILABLE`.
  - Verifica: respx — sucesso, vazio, JSON malformado, 429/5xx, timeout.
  - Arquivos: `news/{port,google_news_rss,gdelt,tavily,fake,chain,cache}.py`, `tests/unit/test_news_providers.py`. Dep.: T0d, T1, T3
- [ ] **T7b — KG: spike e esquema no SurrealDB (banco `kg`)** (M) [07 §2][ADR 0016, 0017]
  - Aceite: spike valida analisador pt-BR (`snowball(portuguese)`), `FULLTEXT` BM25 (acentos/plural), `RELATE` com `TYPE RELATION`, travessias `->`/`<-` com limite de saltos e permissões `kg_writer`/`api_ro`; esquema `kg.surql` + seeds YAML versionados (UFs, regiões, adjacência, patógenos com aliases pt-BR, fontes); `db init` cria o banco `kg` e usuários; achados em ADR 0019.
  - Verifica: testes de seeds (adjacência simétrica, toda UF com região e vizinha, aliases sem colisão) + integração contra o container.
  - Arquivos: `kg/schema/kg.surql`, `kg/seed/*.yaml`, `kg/seeds.py`, `db/init.py`, `tests/…`. Dep.: T3 (skills `srag-graphrag-kg`, `surrealql`, `surrealdb-vector`)
- [ ] **T7c — KG: construção (`build_kg`) com entidades, afirmações e proveniência** (M) [07 §3.1]
  - Aceite: ligação de entidades por dicionário; extração de afirmações pela tarefa `kg.extract_claims` (router + validadores + juiz); upsert idempotente com `produced_by`/`judge`/`expires_at`; reprovados em quarentena; `kg prune` por TTL; eventos `kg_write`/`kg_quarantine` por interface de auditoria.
  - Verifica: corpus rotulado (≈ 30 manchetes) com F1 de entidades ≥ 0,85 e de afirmações ≥ 0,70 (modelo gravado/fake); adversarial (span inventado, injeção) ⇒ 0 nós.
  - Arquivos: `kg/{build,extract,writer,prune}.py`, `tests/fixtures/kg/*`, `tests/…`. Dep.: T6c, T7, T7b, T10
- [x] **T8 — Guardrails G1 (entrada) e G4 (orçamento)** (S) [04] — ✔ (G1 reutiliza `ScopeArgs`, detalhes nunca ecoam a entrada; G4 com tetos por tier, consultas, artigos e prazo; limite de tokens fica para a configuração dos modelos)
  - Aceite: `ReportRequest` estrito (`extra=forbid`, UF, `as_of`, janela 7–90); `Budget` (chamadas LLM, tokens, queries, artigos, timeout); veredito padronizado `GuardrailVerdict`.
  - Verifica: tabela de casos válidos/ inválidos (incl. payload tipo `BR'; REMOVE …`).
  - Arquivos: `guardrails/{verdict,input,budget}.py`, `tests/guardrails/test_input_budget.py`. Dep.: T1
- [ ] **T9 — Trilha de auditoria (hash chain, SurrealDB `audit`)** (M) [05]
  - Aceite: `AuditLog` com eventos `audit.v1`, `seq` único, `prev_hash/hash`, escritor com credencial de mínimo privilégio, falha ⇒ aborta; `audit verify` e `audit export` (JSONL).
  - Verifica: integração — adulteração (editar/remover/reordenar) detectada; credencial da API não faz UPDATE/DELETE; nenhum evento com PII/conteúdo por padrão.
  - Arquivos: `governance/{audit,chain,verify}.py`, `db/schema/audit.surql`, `tests/integration/test_audit.py`. Dep.: T0c, T3
- [ ] **T10 — Guardrail G2 (notícias não confiáveis) + scrubber de PII** (M) [04]
  - Aceite: allowlist/score de domínios, filtros de idioma/data/relevância, dedupe, sanitização (markup, Unicode oculto), detector de instruções, scrubber CPF/CNPJ/e-mail/telefone, empacotamento `<untrusted_news>`.
  - Verifica: corpus ≥ 15 injeções + ≥ 10 PII, todos neutralizados/ bloqueados.
  - Arquivos: `guardrails/{news,pii}.py`, `config/domains.yaml`, `tests/guardrails/test_news_pii.py`. Dep.: T7, T8
- [ ] **T10b — Guardrail G3 (grounding da narrativa)** (M) [04]
  - Aceite: modelos `Claim/Narrative/NewsPlan`; extração de números/datas/URLs; match com métricas/artigos **e `evidence_refs` ⊆ `EvidencePack`** (números de notícias só como "segundo {fonte}"); cobertura M1–M4 e limitações (proxy/maturidade, dias excluídos por `settle_days`); política de conteúdo clínico; verdicts com `rule_id`.
  - Verifica: ≥ 10 narrativas com número inventado/arredondamento indevido/URL falsa bloqueadas; narrativa correta passa.
  - Arquivos: `agent/schemas.py`, `guardrails/grounding.py`, `tests/guardrails/test_grounding.py`. Dep.: T2, T8
- [ ] **T10c — GraphRAG: recuperação (`search_knowledge_graph`) e resumos regionais** (M) [07 §3.2–3.3]
  - Aceite: templates SurrealQL fixos e parametrizados (BM25 + expansão ≤ 2 saltos + resumos regionais via tarefa `kg.summarize_region` com juiz); ranqueamento relevância × confiança × fonte × recência; `EvidencePack` com `evidence_id`/`graph_path`/proveniência; KG desligado/falho ⇒ `KG_UNAVAILABLE` com notícias planas.
  - Verifica: integração (FTS pt-BR, travessia, limites), recall@12 ≥ 0,8 em ≈ 15 perguntas rotuladas; propriedade "todo item tem proveniência".
  - Arquivos: `kg/{retrieve,rank,summaries}.py`, `agent/tools/knowledge_graph.py`, `tests/…`. Dep.: T7c
- [ ] **T11 — Grafo LangGraph + prompts versionados** (M) [01][03 §2][ADR 0001, 0004]
  - Aceite: `StateGraph` com nós `validate → fetch_metrics → plan_news (tier small via router) → collect_news → synthesize (tier large) → verify → render → finalize` (notícias planas; ponto de extensão para o KG); retry único; degradações (`NEWS_UNAVAILABLE`, `NARRATIVE_REJECTED`); wrapper de nó (auditoria + orçamento); prompts em `llm/prompts/*.md` com versão/hash.
  - Verifica: execução completa com fakes; caminho fail-closed (LLM que mente ⇒ relatório degradado sem narrativa); notícias indisponíveis ⇒ degradação; eventos de auditoria completos (T9).
  - Arquivos: `agent/{graph,state,nodes}.py`, `llm/prompts/*.md`, `tests/integration/test_graph.py`. Dep.: T5, T6b, T9, T10, T10b (skills `srag-langgraph`, `langchain-build-agent`, `srag-llm-router-judge`)
- [ ] **T11b — Integrar GraphRAG ao grafo (`build_kg` + `retrieve_context`)** (S) [07][03 §2]
  - Aceite: nós `build_kg` (router small + juiz) e `retrieve_context` entre `collect_news` e `synthesize`; `Narrative` com `evidence_refs`; G3 valida `evidence_id`; degradação `KG_UNAVAILABLE`; `SRAG_KG_ENABLED=false` volta ao fluxo de notícias planas; relatório mostra evidências com `graph_path` e proveniência (quem extraiu/julgou).
  - Verifica: execução completa com fakes e SurrealDB real; caminho KG desligado/falho; auditoria com `kg_write`/`router_decision`/`judge_verdict`.
  - Arquivos: `agent/{graph,nodes,state}.py`, `agent/schemas.py`, `guardrails/grounding.py`, `tests/integration/test_graph_kg.py`. Dep.: T11, T6c, T7c, T10c (skills `srag-graphrag-kg`, `srag-langgraph`)
- [ ] **T12 — Relatório HTML + JSON + gráficos SVG** (M) [02 §7][03 §5]
  - Aceite: matplotlib SVG (diário 30d com média móvel; mensal 12m com mês parcial marcado); Jinja2 autoescape; HTML autocontido com painel de métricas, selo proxy, notícias com links, limitações, proveniência; `report.json` com schema versionado e hashes.
  - Verifica: testes de estrutura/valores; teste XSS com título hostil; CSP/ausência de JS e recursos remotos.
  - Arquivos: `reporting/{charts,render,templates/report.html.j2,models}.py`, `tests/unit/test_reporting.py`. Dep.: T5 (skill `srag-reporting`)
- [ ] **T13 — PDF do relatório (WeasyPrint)** (S) [03 §5]
  - Aceite: PDF gerado do mesmo HTML com `@media print`, A4, metadados; `url_fetcher` bloqueando recursos remotos/`file://`; falha ⇒ `PDF_UNAVAILABLE`; hash no `report.json`.
  - Verifica: smoke (abre, páginas > 0, texto extraível); teste de bloqueio do fetcher.
  - Arquivos: `reporting/pdf.py`, `reporting/templates/print.css`, `tests/unit/test_pdf.py`. Dep.: T12, T0d

### Checkpoint 2b (GraphRAG integrado) — após T6c, T7b, T7c, T10c, T11b
- [ ] `build_kg` + `retrieve_context` rodam ponta a ponta com fakes e SurrealDB real; evidências com `graph_path` e proveniência no relatório; KG desligado mantém o fluxo do CP2; F1/recall nas fixtures nas metas · **revisão humana**

### Checkpoint 2 (relatório completo com fakes)
- [ ] Grafo roda ponta a ponta com fakes gerando HTML, JSON e PDF · guardrails e auditoria verdes · **revisão humana**; rodar uma vez com chave real (Anthropic) para avaliar qualidade da narrativa

## Fase 3 — Serviço, observabilidade e deployment

- [ ] **T14 — API FastAPI + comando `report`** (M) [03 §6]
  - Aceite: `POST /v1/reports`, `GET /v1/reports/{id}?format=json|html|pdf`, `GET /v1/audit/{id}`, `/healthz`, `/readyz`; lifespan com injeção; erros RFC 9457 com `run_id`/`trace_id`; persistência no banco `app`; CLI `report`/`audit verify`.
  - Verifica: testes com `TestClient` + overrides; 422 para entrada inválida; readiness falha sem banco.
  - Arquivos: `api/{app,routes,errors,deps}.py`, `cli.py`, `tests/integration/test_api.py`. Dep.: T11, T12, T13 (skill `srag-fastapi-pydantic`)
- [ ] **T15 — Instrumentação OpenTelemetry** (M) [06 §2]
  - Aceite: provider OTLP (traces, métricas, logs JSON com `trace_id`); spans por nó/tool/LLM/guardrail/`router.task`/`judge.evaluate`/`kg.*` com atributos GenAI (sem conteúdo); métricas `srag.*` da spec (incluindo `srag.router.*`, `srag.judge.*`, `srag.kg.*`); `run_id` correlacionando auditoria.
  - Verifica: teste com exporter em memória (spans esperados, nenhum atributo com payload/PII).
  - Arquivos: `observability/{setup,metrics,logging}.py`, wrapper em `agent/nodes.py`, `tests/unit/test_otel.py`. Dep.: T14 (skill `otel-python`)
- [ ] **T16 — Docker e Compose "prod-like"** (M) [06 §1,3]
  - Aceite: Dockerfile multi-stage não-root/read-only com libs do WeasyPrint e `LLM_EXTRAS`; `compose.yaml` com surrealdb (sem porta pública), app, ingest (profile), otel-collector, jaeger, prometheus, grafana; redes `frontend/data/telemetry`; healthchecks; tags fixas; `docker compose config` válido.
  - Verifica: `docker compose up --build` saudável em clone limpo; `db init` + `ingest` + `POST /v1/reports` produzem relatório; trace visível no Jaeger.
  - Arquivos: `Dockerfile`, `compose.yaml`, `.dockerignore`, `observability/{otel-collector.yaml,prometheus.yml}`. Dep.: T14, T15 (skill `srag-docker-observability-stack`)
- [ ] **T17 — Dashboards e alertas Grafana/Prometheus** (S) [06 §2]
  - Aceite: datasources e dashboards provisionados (volume/degradação, latência por nó, tokens/custo, guardrails, frescor de dados); regras de alerta de exemplo.
  - Verifica: após um relatório, painéis exibem dados (captura de tela no README).
  - Arquivos: `observability/grafana/**`, `observability/alerts.yml`. Dep.: T16
- [ ] **T18 — CI (GitHub Actions)** (S) [06 §5]
  - Aceite: jobs lint, types, test (cobertura ≥ 85 %), security (gitleaks, audit de deps, Trivy), build, e2e (compose + fakes), diagram check.
  - Verifica: workflow verde no PR; falha proposital (ex.: segredo falso) é detectada.
  - Arquivos: `.github/workflows/ci.yml`, `.gitleaks.toml`. Dep.: T16
- [ ] **T19 — Diagrama conceitual em PDF** (S) [01 §7] — **entregável do desafio**
  - Aceite: fonte em **Mermaid** (`docs/architecture/architecture.md`, já criado) → `docs/architecture/architecture.pdf` (comando `docker compose run --rm diagram` com `mermaid-cli`) mostrando Orquestrador, Tools (incl. `search_knowledge_graph`), LLM Router/Judge e tiers, 4 provedores, SurrealDB (`data`, `kg`, `audit`, `app`), fontes de notícias, guardrails, auditoria e pipeline OTel; PDF commitado. Mermaid-cli roda Chromium em container. **Validado em 2026-11-16:** os 6 diagramas atuais renderizam com `minlag/mermaid-cli` usando um `puppeteer.json` com `executablePath: /usr/lib/chromium/chromium` e `--no-sandbox` (só dentro do container efêmero); fixar a tag da imagem no Compose.
  - Verifica: PDF abre e é legível em A4/paisagem; CI renderiza os diagramas (falha se a sintaxe Mermaid quebrar) e detecta divergência fonte × PDF.
  - Arquivos: `docs/architecture/architecture.{dot,pdf}`, serviço `diagram` no Compose. Dep.: T11

### Checkpoint 3
- [ ] Stack completa sobe do zero · CI verde · diagrama pronto · **revisão humana**

## Fase 4 — Endurecimento e entrega

- [ ] **T20 — Corpus adversarial, conformidade de provedores e e2e** (M) [04 §5][SPEC §8]
  - Aceite: corpus completo da spec (injeção, grounding, PII, parâmetros, orçamento, fail-closed, `api_ro` sem escrita, **envenenamento do KG e manipulação do juiz**); avaliações do GraphRAG/router: F1 de extração (small × large), recall@K, concordância juiz × humano (κ ≥ 0,6), taxa de escalada (meta ≥ 70 % resolvido em `small`) e custo vs. baseline "tudo large"; e2e via Compose; teste `live` por provedor (Anthropic/Gemini/NIM/OpenRouter) executado com as chaves disponíveis e resultado registrado; metas de latência p95 ≤ 90 s medidas.
  - Verifica: `pytest -m "not live"` verde; relatório de conformidade em `docs/provider-conformance.md`.
  - Arquivos: `tests/e2e/*`, `tests/guardrails/corpus/*`, `docs/provider-conformance.md`. Dep.: T14–T16
- [ ] **T21 — README, ADRs e model card** (M) — **entregável do desafio**
  - Aceite: README (visão, arquitetura com os diagramas Mermaid + link do PDF, GraphRAG/KG e router/judge explicados, quickstart `docker compose up`, decisões, métricas e proxies explicados, guardrails, PII/LGPD, governança/auditoria, observabilidade com capturas, troubleshooting, caminho para produção, limitações/model card); ADRs 0001–0019 completos; SPEC.md com status "implementado".
  - Verifica: um revisor segue só o README num clone limpo e obtém o relatório; links internos válidos.
  - Arquivos: `README.md`, `docs/adr/*.md`, `SPEC.md`. Dep.: T19, T20

### Checkpoint 4 (entrega)
- [ ] Todos os critérios de sucesso da SPEC §8 marcados com evidência · repositório público · **revisão humana final**
