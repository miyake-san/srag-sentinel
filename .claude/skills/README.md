# Skills do projeto

Skills (formato `SKILL.md`) que dão contexto especializado a agentes de código (Claude Code e outros compatíveis) para cada stack do projeto. Dois grupos: **incorporadas de terceiros** (oficiais, revisadas) e **próprias** (`srag-*`, escritas para este repositório com referências pesquisadas e verificadas em 2026-11-16).

## Mapa stack → skill

| Stack | Skill(s) | Origem |
|---|---|---|
| SurrealDB (linguagem, perf, funções, SDK Python, CLI, vetores/HNSW) | `surrealql`, `surrealql-performance`, `surrealql-functions`, `surrealdb-python`, `surrealdb-cli`, `surrealdb-vector` | oficial SurrealDB (MIT) |
| GraphRAG e grafo de conhecimento | `srag-graphrag-kg` | própria |
| LLM Router e Judge | `srag-llm-router-judge` | própria |
| SurrealDB — decisões deste projeto | `srag-surrealdb-conventions` | própria |
| LangChain / LangGraph / Deep Agents (escolha de arquitetura) | `langchain-build-agent` | oficial LangChain (MIT) |
| LangGraph — convenções do orquestrador | `srag-langgraph` | própria |
| Provedores de LLM (Anthropic, Gemini, NVIDIA NIM, OpenRouter) | `srag-llm-providers` | própria |
| Python tooling (uv, ruff) | `uv`, `ruff` | oficial Astral (MIT/Apache-2.0) |
| OpenTelemetry em Python | `otel-python` | OllyGarden (Apache-2.0) |
| Docker, Compose, Collector/Jaeger/Prometheus/Grafana, CI | `srag-docker-observability-stack` | própria |
| FastAPI + Pydantic | `srag-fastapi-pydantic` | própria (não há skill oficial do FastAPI; só skills de comunidade, não incorporadas) |
| pytest, hypothesis, respx, mypy | `srag-testing` | própria |
| Relatório: matplotlib, Jinja2, WeasyPrint (PDF) | `srag-reporting` | própria |
| Notícias (GDELT) | `srag-news-gdelt` | própria |
| Ingestão Open DATASUS (CKAN, Polars) | `srag-datasus-ingest` | própria |
| Guardrails, PII, auditoria | `srag-security-guardrails` | própria |

## Proveniência das skills de terceiros

Copiadas por revisão manual de `git clone` raso (nenhum script foi executado). Licenças em [`_third_party_licenses/`](_third_party_licenses/).

| Repositório | Commit | Skills copiadas | Licença |
|---|---|---|---|
| [surrealdb/agent-skills](https://github.com/surrealdb/agent-skills) | `b139bf7` | `surrealql`, `surrealql-performance`, `surrealql-functions`, `surrealdb-python`, `surrealdb-cli`, `surrealdb-vector` (adicionada para o GraphRAG) | MIT |
| [langchain-ai/langchain-skills](https://github.com/langchain-ai/langchain-skills) | `8f4f0a4` | `langchain-build-agent` | MIT |
| [astral-sh/claude-code-plugins](https://github.com/astral-sh/claude-code-plugins) | `855418f` | `uv`, `ruff` | MIT ou Apache-2.0 |
| [ollygarden/opentelemetry-agent-skills](https://github.com/ollygarden/opentelemetry-agent-skills) | `eac2a29` | `otel-python` (SKILL.md + references; sem scripts/evals) | Apache-2.0 |

**Não incorporadas, de propósito**

- `surrealdb-docs` e `surrealdb-agent-memory-docs` (SurrealDB): pré-autorizam `curl`/`ssh` no front-matter (`allowed-tools`); não são necessárias.
- `surrealdb-js`, `surrealkit`: fora do escopo (sem JS; migrações ficam em `src/srag_sentinel/db/schema/*.surql`). `surrealdb-vector` entrou com o GraphRAG (estágio opcional com HNSW).
- `ty` (Astral): usamos `mypy`.
- Demais skills de LangChain (`langchain-agent-tracing`, `-monitoring`, `-eval-engineering`): voltadas ao LangSmith, trazem scripts; não usamos LangSmith (telemetria é OpenTelemetry).
- Skills de comunidade (FastAPI etc.): qualidade e origem variáveis; preferimos skill própria com links oficiais.
- `otel-semantic-conventions`, `otel-sdk-versions`, `otel-declarative-config` (OllyGarden): `otel-python` as cita como complementares; os scripts delas usam `curl` e não foram copiados. Se necessário, incorpore após revisão.

## Cuidados

- Skill é instrução para o agente: **revise antes de atualizar** qualquer skill de terceiros (diff completo) e registre o novo commit na tabela acima.
- Conteúdo de terceiros pode estar defasado em relação às versões fixadas no `uv.lock` (ex.: `surrealdb-python` fala em modo embarcado; usamos servidor remoto). Em caso de conflito, valem a spec do projeto e a documentação oficial da versão instalada.
- Skills próprias estão em inglês (instruções para agentes, como código e commits); specs e README em português.
- `surrealdb-cli/SKILL.md` cita um instalador `curl … | sh` apenas como texto de referência; **não** o execute — o SurrealDB roda pela imagem Docker fixada no Compose. Também não rode `npx skills add`: as skills já estão no repositório.
