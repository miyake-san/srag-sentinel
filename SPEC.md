# Spec: SRAG Sentinel

> Status: **implementado (PoC) — com ressalvas** · Data de referência das versões: 2026-11-16
> O código segue esta spec; o que ficou de fora ou não foi medido está em [`README.md`](README.md#limitações-e-model-card), [`docs/evaluation.md`](docs/evaluation.md) e [`tasks/todo.md`](tasks/todo.md). Diferenças conhecidas: relatórios em arquivos (não no banco `app`), cache de notícias em memória, vetores (HNSW) e Tavily adiados, sem telemetria de tokens/custo.
> Rev. 2: decisões do usuário incorporadas (provedores de LLM, SurrealDB, PDF do relatório, skills do repo) — ver §9.
> Specs detalhadas: [`docs/specs/`](docs/specs/) · ADRs: [`docs/adr/`](docs/adr/)

## 1. Objetivo

Construir uma PoC para a **HealthCare Co., empresa fictícia** criada para este exercício (qualquer semelhança com empresas reais é coincidência), de um **agente de IA generativa** que gera, de forma automatizada, um **relatório de situação de SRAG** (Síndrome Respiratória Aguda Grave) para profissionais de saúde, combinando:

1. **Métricas determinísticas** calculadas sobre o banco SRAG do Open DATASUS (via ferramenta de consulta);
2. **Contexto de notícias em tempo real** (via ferramenta de busca de notícias) para embasar e explicar o cenário;
3. **Narrativa gerada por LLM**, estritamente ancorada nas métricas e nas evidências recuperadas.
4. **GraphRAG sobre um grafo de conhecimento no SurrealDB** (UFs, regiões, patógenos, artigos, afirmações, snapshots das métricas), cujas tarefas "baratas" rodam em **LLMs pequenos** roteados por um **LLM Router + LLM Judge** ([07](docs/specs/07-graphrag-knowledge-graph.md), [08](docs/specs/08-llm-router-judge.md)).

**Usuário:** profissional de vigilância/gestão em saúde que quer entender severidade e avanço de surtos.
**Entrega do desafio:** repositório público, README com toda a documentação e um **PDF com o diagrama conceitual** (Orquestrador, Tools, LLM, banco de dados, fontes de notícias).

**Critérios de avaliação do desafio → onde estão cobertos**

| Critério | Spec |
|---|---|
| Escolha da arquitetura | [01-architecture](docs/specs/01-architecture.md), [03-agent-and-tools](docs/specs/03-agent-and-tools.md), [07-graphrag](docs/specs/07-graphrag-knowledge-graph.md), [08-router-judge](docs/specs/08-llm-router-judge.md), [diagramas Mermaid](docs/architecture/architecture.md) |
| Governança e transparência (auditoria, registro de decisões) | [05-governance-audit](docs/specs/05-governance-audit.md) |
| Guardrails | [04-guardrails-security](docs/specs/04-guardrails-security.md) |
| Tratamento de dados sensíveis | [04-guardrails-security](docs/specs/04-guardrails-security.md) §PII, [02-data-and-metrics](docs/specs/02-data-and-metrics.md) §Minimização |
| Clean code | §4 (estilo), §5 (testes), §6 (fronteiras) deste documento |

### Escopo

**Dentro:** 4 métricas, 2 gráficos, narrativa com citações, API + CLI, auditoria, guardrails, observabilidade OTel, deployment via Docker Compose, diagrama em PDF.
**Fora (PoC):** UI web interativa, autenticação multiusuário, nowcasting estatístico, dados populacionais externos (IBGE/PNI/CNES), treinamento de modelos, deploy em nuvem/Kubernetes (apenas documentado como evolução).

### Premissas (corrija agora ou seguirei com elas)

1. **Python 3.14** (3.14.10; **decisão da T0a** — ver [ADR 0008](docs/adr/0008-python-version.md)): 3.15.2 já é estável, mas `zstandard` (via langchain-core → langsmith) e `pyyaml` não têm wheel cp315, o que exigiria compilador; reavaliar 3.15 quando houver wheels. Gerenciado com **uv**.
2. **LangGraph** como orquestrador (grafo explícito, não loop ReAct livre) + **LangChain** para abstração de LLM, **provider-agnóstico** com 4 provedores suportados: **Anthropic (default, `claude-sonnet-5-5`)**, **Google Gemini**, **NVIDIA NIM** (API Catalog ou NIM self-hosted) e **OpenRouter**; escolha por `SRAG_LLM_PROVIDER` + `SRAG_LLM_MODEL` ([03](docs/specs/03-agent-and-tools.md) §4).
3. **Dados:** dataset vigente "SRAG 2019 a 2026" em `dadosabertos.saude.gov.br` (o link `opendatasus.saude.gov.br/dataset/srag-2021-a-2024` do enunciado redireciona para o novo portal; o dataset 2021–2024 foi substituído). Usaremos os recursos **Parquet** por ano (2025 e 2026 por padrão), licença CC BY-ND 3.0.
4. **Banco de dados: SurrealDB** (servidor em container, SDK Python `surrealdb`), com **bancos lógicos separados no mesmo namespace**: `data` (agregados diários SRAG), `audit` (trilha de auditoria) e `app` (relatórios gerados, cache de notícias). Somente **agregados diários por UF** entram no banco — nenhuma linha individual de paciente ([02](docs/specs/02-data-and-metrics.md)). Sem text-to-SQL: o agente só chama **funções de métrica parametrizadas** que executam SurrealQL com variáveis.
5. **Notícias:** `NewsProvider` plugável com **cadeia de provedores** (decisão do usuário após o spike T0d, [ADR 0014](docs/adr/0014-news-and-pdf-findings.md)): **Google News RSS pt-BR (primário, sem chave)** → **GDELT DOC 2.0 (secundário, sem chave, best-effort por causa do limite de 1 req/5 s)** → **Tavily (opcional, com chave)**. Resultados dos provedores são unidos, deduplicados e filtrados pelo G2; falha de todos ⇒ `NEWS_UNAVAILABLE`.
6. **Relatório em pt-BR** em **três formatos: HTML autocontido, JSON e PDF** (confirmado). Código, identificadores e commits em inglês; README e specs em português.
7. **Execução:** `docker compose up` sobe SurrealDB, API (FastAPI), job de ingestão, OTel Collector, Jaeger, Prometheus e Grafana. Também há CLI (`srag-sentinel report`).
8. **Auditoria** é uma trilha append-only com cadeia de hash armazenada no **banco `audit` do SurrealDB** (com exportação JSONL para arquivamento), separada da telemetria OTel; ver [05](docs/specs/05-governance-audit.md).
9. **Skills do repositório** (`.claude/skills/`): skills oficiais de terceiros (SurrealDB, LangChain, Astral, OpenTelemetry) copiadas com licença e proveniência, mais skills próprias por stack com referências verificadas — ver [`.claude/skills/README.md`](.claude/skills/README.md).
10. **Python × SDK SurrealDB:** SDK 3.0.0 (wheel puro, suporte declarado até 3.14) instala e importa em Python 3.14 (T0a ✔).
11. **GraphRAG leve e grafo de conhecimento no SurrealDB** (banco lógico `kg`; [ADR 0016](docs/adr/0016-graphrag-on-surrealdb.md), [0017](docs/adr/0017-knowledge-graph-model.md)): ontologia fechada, recuperação híbrida **BM25 + travessia de arestas** + resumos regionais; **vetores/HNSW opcionais** (flag, exigem provedor de embeddings). Nenhuma consulta é gerada por LLM.
12. **LLM Router + Judge** ([ADR 0018](docs/adr/0018-llm-router-and-judge.md)): tabela estática tarefa → camadas (`small → large`) com **validadores determinísticos primeiro** e juiz LLM só em casos ambíguos; sem dependência nova; a síntese final fica sempre no tier `large`.

> ⚠️ **Limitação dos dados que afeta duas métricas — aproximações aceitas pelo usuário** (detalhe em [02](docs/specs/02-data-and-metrics.md)): o dataset não traz leitos nem população. Portanto **"taxa de ocupação de UTI"** será a *proporção de casos hospitalizados que usaram UTI* e **"taxa de vacinação da população"** será a *proporção de casos SRAG vacinados* (COVID e influenza). Ambas são rotuladas como *proxy* no relatório. Ocupação real e cobertura populacional exigiriam fontes externas (CNES/ocupação hospitalar, SI-PNI + IBGE) — fora do escopo, listadas como *Ask first*.

## 2. Tech stack (baseline verificado em 2026-11-16)

| Camada | Escolha | Versão baseline |
|---|---|---|
| Linguagem | Python | 3.14.x |
| Gerenciador | uv (lockfile commitado) | latest |
| Orquestração | langgraph | 1.2.x |
| LLM abstraction | langchain + extras por provedor: `langchain-anthropic`, `langchain-google-genai`, `langchain-nvidia-ai-endpoints`, `langchain-openrouter` | langchain 1.5.x |
| Validação/Config | pydantic, pydantic-settings | 2.14.x |
| API | FastAPI + uvicorn | 0.163.x |
| Banco de dados | SurrealDB (servidor em container) + SDK Python `surrealdb` (async) | server 4.0.1 · SDK 3.0.0 |
| Ingestão | Polars (leitura de Parquet e agregação diária) | latest |
| Relatório | matplotlib (SVG estático), Jinja2, WeasyPrint (PDF) | WeasyPrint 70.x |
| Notícias | httpx + `defusedxml` (RSS do Google News), GDELT DOC 2.0 | latest |
| GraphRAG / KG | SurrealDB: arestas (`RELATE`), `FULLTEXT` BM25 pt-BR, HNSW opcional; seeds YAML (`pyyaml`, já transitiva) | server 4.0.1 |
| LLM Router / Judge | código próprio sobre a fábrica de provedores; política em YAML validada por Pydantic | sem dependência nova |
| Observabilidade | opentelemetry-sdk + OTLP exporter | 1.45.x |
| Qualidade | ruff, mypy (strict), pytest, pytest-cov, hypothesis | latest |
| Container | Docker, Compose v2; imagem `python:3.14-slim` multi-stage | — |
| Infra de telemetria | OTel Collector, Jaeger, Prometheus, Grafana | imagens com tag fixa |

Versões exatas ficam no `uv.lock` e nas tags de imagem; dependências novas além desta tabela = *Ask first*.

## 3. Comandos

```bash
# setup
uv sync --frozen
# qualidade
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest --cov=srag_sentinel --cov-report=term-missing --cov-fail-under=85
# dados
docker compose up -d surrealdb                          # banco local (necessário para ingest/report)
uv run srag-sentinel db init                            # aplica db/schema/*.surql (idempotente)
uv run srag-sentinel ingest --years 2025 2026           # baixa Parquet -> data/raw, agrega por dia/UF -> SurrealDB
# relatório (html, json e pdf)
uv run srag-sentinel report --as-of auto --uf BR --out reports/
# provedor de LLM alternativo (extras): uv sync --extra google|nvidia|openrouter
SRAG_LLM_PROVIDER=google_genai SRAG_LLM_MODEL=<modelo> uv run srag-sentinel report
# stack completa (API + telemetria)
docker compose up --build
curl -X POST localhost:8000/v1/reports -H 'content-type: application/json' -d '{"uf":"BR"}'
# diagrama (fonte -> PDF)
docker compose run --rm diagram     # docs/architecture/architecture.dot -> architecture.pdf
```

> Cada comando listado deve existir e funcionar ao fim da implementação; mudanças viram atualização desta seção.

## 4. Estrutura do projeto

```
srag-sentinel/
├── SPEC.md                      # este documento
├── README.md                    # doc principal (entregável)
├── pyproject.toml  uv.lock
├── Dockerfile  compose.yaml  .env.example
├── .claude/skills/              # skills do projeto (vendored + próprias) e README de proveniência
├── compose.yaml  compose.dev.yaml  # stack (hoje só SurrealDB) + override de dev (porta em localhost)
├── docs/
│   ├── specs/                   # specs detalhadas (01..06)
│   ├── adr/                     # decisões de arquitetura (NNNN-titulo.md)
│   └── architecture/            # architecture.dot -> architecture.pdf (entregável)
├── observability/               # otel-collector.yaml, prometheus.yml, grafana provisioning
├── src/srag_sentinel/
│   ├── domain/                  # puro: modelos, definições de métricas, sem I/O
│   ├── db/                      # cliente SurrealDB, `init` idempotente e schema/*.surql (pacote)
│   ├── data/                    # ingestão (Parquet -> agregados) e repositório SurrealDB (porta + adaptador)
│   ├── news/                    # NewsProvider (porta) + google_news_rss/gdelt/tavily (adaptadores) + cadeia
│   ├── llm/                     # fábrica de provedores (anthropic/google/nvidia/openrouter), prompts versionados
│   │   └── router/              # policy.yaml, cascata, validadores, juiz (spec 08)
│   ├── kg/                      # seeds, esquema, construção (build_kg) e recuperação (GraphRAG) — spec 07
│   ├── agent/                   # grafo LangGraph, estado, nós, tools
│   ├── guardrails/              # entrada, notícias, saída, orçamento
│   ├── governance/              # trilha de auditoria (hash chain), registro de decisões
│   ├── reporting/               # gráficos, template HTML, serialização JSON
│   ├── observability/           # setup OTel (traces/metrics/logs)
│   ├── api/                     # FastAPI
│   ├── cli.py
│   └── settings.py
├── tests/
│   ├── unit/  integration/  guardrails/  e2e/
│   └── fixtures/                # mini-dataset sintético, notícias, respostas LLM gravadas
└── data/                        # gitignored (raw/ — staging temporário dos Parquet baixados)
```

Regra de dependência: `domain` não importa nada de fora; `agent` depende de portas (protocolos), nunca de adaptadores concretos; adaptadores são injetados em `api`/`cli` (composition root).

## 5. Estilo de código

Tipagem completa, modelos imutáveis, funções pequenas e puras no domínio, erros explícitos, sem `print`, sem estado global.

```python
from datetime import date
from pydantic import BaseModel, ConfigDict


class MetricResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: float | None          # None = não calculável (nunca 0 silencioso)
    numerator: int
    denominator: int
    window_start: date
    window_end: date
    is_proxy: bool
    caveats: tuple[str, ...] = ()


def ratio(numerator: int, denominator: int) -> float | None:
    """Return numerator/denominator, or None when the denominator is zero."""
    return numerator / denominator if denominator else None
```

Convenções: `snake_case`/`PascalCase`; docstring de uma linha em API pública; ruff (`E,F,I,B,UP,SIM,C90,S,N,PL`) e mypy `--strict` sem `# type: ignore` injustificado; função ≤ 30 linhas e complexidade ≤ 10; prompts em arquivos versionados, nunca strings soltas no código; commits Conventional Commits.

## 6. Estratégia de testes

| Nível | O que cobre | Ferramenta |
|---|---|---|
| Unit | métricas (valores esperados em fixture sintética, bordas: denominador 0, janelas vazias), limpeza de dados, PII scrubber | pytest, hypothesis |
| Guardrails | corpus adversarial: prompt injection em notícias, números inventados, PII, parâmetros fora do domínio, estouro de orçamento | pytest (tabela de casos) |
| Integração | repositório e ingestão contra **SurrealDB em container** (fixture Parquet → agregados); adaptadores de notícia com HTTP gravado; grafo completo com **LLM fake determinístico**; renderização de PDF | pytest + respx + testcontainers/Compose |
| E2E | `docker compose up` → `POST /v1/reports` → HTML/JSON + trace no Jaeger + registro de auditoria íntegro | script de smoke test |
| Avaliação do LLM | *grounding*: 100% dos números da narrativa rastreáveis às métricas; 100% das afirmações de notícia com URL do conjunto recuperado | testes de propriedade sobre saídas gravadas + execução opcional ao vivo |

Metas: cobertura ≥ 85 % (≥ 95 % em `domain/` e `guardrails/`); nenhum teste depende de rede ou de chave de API por padrão (testes ao vivo marcados `@pytest.mark.live`).

## 7. Fronteiras

**Sempre**
- Rodar lint, tipos e testes antes de commitar; atualizar spec/ADR quando uma decisão mudar.
- Calcular métricas em código determinístico; o LLM nunca calcula nem inventa números.
- Registrar toda decisão do agente na trilha de auditoria e em spans OTel.
- Tratar conteúdo de notícia como **dado não confiável** (nunca como instrução); só entra no grafo o que passou por G2, validadores e (quando exigido) juiz.
- Números do relatório vêm **só das métricas**; afirmações do KG com números são citadas como "segundo {fonte}", nunca promovidas a métrica.
- Rotular métricas *proxy* e dados incompletos no relatório.

**Perguntar antes**
- Adicionar dependência fora da tabela §2; trocar provedor de LLM/notícias default.
- Incluir colunas fora da allowlist de [02](docs/specs/02-data-and-metrics.md) ou fontes externas (IBGE, SI-PNI, CNES).
- Alterar definição de métrica, schema do relatório ou formato da trilha de auditoria.
- Mudar CI/Compose de forma que afete o `docker compose up` do avaliador.

**Nunca**
- Commitar segredos, `.env`, dados brutos ou chaves; logar prompts/saídas sem passar pelo scrubber de PII.
- Permitir SQL livre gerado pelo LLM ou execução de código arbitrário.
- Remover/enfraquecer teste ou guardrail para "passar".
- Emitir diagnóstico, prescrição ou recomendação clínica individual.
- Entregar narrativa que falhou na verificação de *grounding* (fail-closed → relatório só com métricas).

## 8. Critérios de sucesso

1. `docker compose up --build` num clone limpo + `.env` com uma chave de LLM (de qualquer um dos 4 provedores) entrega um relatório válido via `POST /v1/reports` em ≤ 90 s (p95, excluindo ingestão).
2. O relatório, em **HTML, JSON e PDF** (mesmo conteúdo e mesmos hashes de proveniência), contém as **4 métricas** (valor, numerador/denominador, janela, rótulo proxy quando aplicável) e os **2 gráficos** (diário 30 dias; mensal 12 meses), com avisos de maturidade dos dados.
2a. Os 4 provedores de LLM (Anthropic, Gemini, NVIDIA NIM, OpenRouter) passam no mesmo teste de conformidade (saída estruturada `Narrative`); trocar de provedor exige apenas variáveis de ambiente.
2b. Os dados vivem no SurrealDB (`data`, `kg`, `audit`, `app`); o usuário de leitura da API não consegue escrever em `data`/`kg`/`audit` (verificado por teste).
2c. O relatório cita ≥ 1 `evidence_id` recuperado pelo GraphRAG, com `graph_path` e proveniência (quem extraiu/julgou), quando houver notícias relevantes; com o KG desligado, o sistema segue com notícias planas.
2d. Todas as tarefas de GraphRAG passam pelo router; cada decisão de roteamento/juiz está na auditoria e no trace; a concordância juiz × humano nas fixtures atinge a meta (κ ≥ 0,6).
3. A narrativa cita ≥ 1 notícia recuperada com URL/fonte/data; **0 números não rastreáveis** às métricas (verificado automaticamente).
4. Um trace OTel único por relatório mostra spans de cada nó/tool/chamada LLM no Jaeger; métricas de custo/latência/guardrails visíveis no Grafana.
5. Cada execução gera registro de auditoria encadeado; `srag-sentinel audit verify` detecta adulteração em teste.
6. Corpus adversarial: 100 % dos casos de prompt injection/PII/parâmetro inválido são bloqueados ou neutralizados.
7. Nenhum dado pessoal (identificadores, texto livre) sai do processo para o LLM, logs ou traces; allowlist de colunas aplicada e testada.
8. Falha do provedor de notícias ou do LLM degrada com elegância (relatório parcial sinalizado), sem erro 500.
9. Repositório público com README completo, `docs/architecture/architecture.pdf`, CI verde (lint, tipos, testes, build da imagem).

## 9. Decisões confirmadas e perguntas em aberto

**Confirmadas pelo usuário (rev. 2)**

| # | Decisão |
|---|---|
| 1 | LLM padrão **Anthropic**; também suportados **Gemini, NVIDIA NIM e OpenRouter** |
| 2 | Janela padrão das métricas: **30 dias** |
| 3 | Escopo padrão: **Brasil inteiro**, filtro opcional por UF |
| 4 | Notícias: **Google News RSS → GDELT** (ambos sem chave; Tavily opcional) — revisada após o spike T0d |
| 5 | UTI e vacinação: **métricas aproximadas (proxy)**, sem fonte externa na PoC |
| 6 | Relatório também em **PDF** (além de HTML e JSON) |
| 7 | Banco de dados: **SurrealDB** (skills oficiais do SurrealDB incorporadas ao repo) |
| 8 | **Skills por stack** no repo; onde não há skill pronta, skill própria com referências pesquisadas |
| 9 | **GraphRAG + grafo de conhecimento** no SurrealDB (specs 07, ADRs 0016/0017) — o banco serve também ao GraphRAG |
| 10 | **LLM Router + Judge** para rotear LLMs pequenos nas tarefas de GraphRAG; forma mais simples: tabela estática + cascata + validadores primeiro (spec 08, ADR 0018) |
| 11 | Diagrama de arquitetura em **Mermaid** (`docs/architecture/architecture.md`); o PDF entregável é gerado dele |
| 12 | Correção da M1: `settle_days=3` e ingestão exige ≥ 2 arquivos anuais (ADR 0015) |

**Em aberto (resolvidas na tarefa 0 — spike técnico)**

1. ~~Compatibilidade Python 3.15~~ — **resolvida na T0a: Python 3.14** (ADR 0008). WeasyPrint nativo ainda a validar no Docker (T0d).
2. **Modelos default** de Gemini/NIM/OpenRouter: ids mudam rápido; ficam sem default no código e exemplificados no `.env.example` (confirmar na tarefa 0 com chave real).
3. ~~Append-only no SurrealDB~~ — **resolvida na T0c** ([ADR 0013](docs/adr/0013-surrealdb-findings.md)): viável via record access + `PERMISSIONS … WHERE $access = 'audit_writer'` + `READONLY` + `UNIQUE(seq)`; limite: EDITOR/root ainda apagam (mitigado por hash chain e exportação).
4. ~~Sintaxe/perf das consultas SurrealQL de agregação~~ — sintaxe e injeção validadas na T0c; desempenho a medir na T3.
5. ~~Colunas do dicionário e endpoint CKAN~~ — **resolvida na T0b** ([ADR 0012](docs/adr/0012-datasus-findings.md)): API CKAN não existe (404); link do arquivo extraído da página do recurso; 8 colunas validadas.

## 10. Índice das specs detalhadas

| # | Documento | Conteúdo |
|---|---|---|
| 01 | [architecture](docs/specs/01-architecture.md) | visão, componentes, fluxo, ADRs, diagrama |
| 02 | [data-and-metrics](docs/specs/02-data-and-metrics.md) | fonte, colunas, limpeza, definições exatas das métricas e gráficos |
| 03 | [agent-and-tools](docs/specs/03-agent-and-tools.md) | grafo LangGraph, estado, tools, prompts, contrato do relatório |
| 04 | [guardrails-security](docs/specs/04-guardrails-security.md) | guardrails por camada, PII, ameaças |
| 05 | [governance-audit](docs/specs/05-governance-audit.md) | trilha de auditoria, registro de decisões, reprodutibilidade |
| 06 | [observability-deployment](docs/specs/06-observability-deployment.md) | OTel, Compose, Dockerfile, CI |
| 07 | [graphrag-knowledge-graph](docs/specs/07-graphrag-knowledge-graph.md) | grafo de conhecimento no SurrealDB, construção, recuperação híbrida, segurança, avaliação |
| 08 | [llm-router-judge](docs/specs/08-llm-router-judge.md) | tiers small/large, política de roteamento, cascata, juiz, auditoria |
| 09 | [agent-and-api-security](docs/specs/09-agent-and-api-security.md) | perímetro da API, endurecimento de detecção/PII, condições para um chat ([validação](docs/security-validation.md)) |
| — | [architecture.md](docs/architecture/architecture.md) | diagramas Mermaid (contexto, fluxo, router/judge, KG, ingestão, implantação) |
| — | [`.claude/skills/README.md`](.claude/skills/README.md) | skills do projeto: origem, licença, o que foi (e não foi) incorporado |
