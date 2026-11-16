# 07 — GraphRAG e Grafo de Conhecimento (SurrealDB)

Parte de [SPEC.md](../../SPEC.md). Decisões: [ADR 0016](../adr/0016-graphrag-on-surrealdb.md) (GraphRAG) e [ADR 0017](../adr/0017-knowledge-graph-model.md) (modelo do grafo). Roteamento dos LLMs pequenos: [08](08-llm-router-judge.md). Diagrama: [architecture.md §4](../architecture/architecture.md).

## 1. Objetivo

O SurrealDB não guarda só os agregados do DATASUS: ele hospeda também um **grafo de conhecimento (KG)** que liga *onde* (UFs, regiões), *o quê* (patógenos), *o que foi dito* (artigos e afirmações extraídas das notícias) e *o que o sistema mediu* (snapshots das métricas por relatório). O **GraphRAG** usa esse grafo para recuperar **evidências citáveis** que expliquem o cenário (ex.: "por que os casos sobem no Sul?") e entregá-las ao LLM de síntese, em vez de jogar no prompt uma lista plana de manchetes.

**Resultados esperados**
1. Narrativa com contexto **regional e por patógeno** (vizinhança geográfica, mesma região, mesmo agente), não só notícias isoladas.
2. **Memória entre relatórios** (o que o relatório anterior dizia sobre a UF) via snapshots.
3. **Rastreabilidade**: toda afirmação usada na narrativa aponta para `evidence_id` → artigo/afirmação → fonte, com quem extraiu e quem julgou.
4. Tarefas "baratas" de GraphRAG executadas por **LLMs pequenos** (router + judge, spec 08), mantendo o modelo grande para a síntese.

**Fora do escopo (PoC):** detecção de comunidades (Leiden) em grafo grande, reconciliação multi-fonte de entidades além do dicionário, grafo de pacientes (nenhum dado individual entra no KG), embeddings obrigatórios.

## 2. Modelo do grafo

Banco lógico `kg` no namespace do projeto. Nós = tabelas; arestas = tabelas `TYPE RELATION` criadas com `RELATE`. Ver diagrama ER em [architecture.md](../architecture/architecture.md).

### 2.1 Nós

| Tabela | Origem | Campos principais |
|---|---|---|
| `uf` | seed estático (27 UFs + `BR`) | `code`, `name`, `region` |
| `region` | seed estático (Norte, Nordeste, Centro-Oeste, Sudeste, Sul) | `code`, `name` |
| `pathogen` | seed (ontologia) | `id`, `name_pt`, `aliases[]` — influenza (A/B), SARS-CoV-2/COVID-19, vírus sincicial respiratório (VSR), rinovírus, metapneumovírus, adenovírus, parainfluenza, "SRAG não especificada" |
| `source` | derivado do domínio do artigo | `domain`, `trust` (allowlist de G2: 0–1), `kind` (agência, imprensa, instituição) |
| `article` | notícias coletadas (G2 já aplicado) | `id` (hash da URL canônica), `title`, `url`, `published_at`, `snippet`, `lang`, `sha256`, `retrieved_at`, `run_id` |
| `claim` | extração por LLM pequeno | `id`, `type`, `text`, `evidence_span`, `direction`, `confidence`, `extractor` (`tier/modelo/prompt@versão`), `judge` (veredito), `expires_at` |
| `snapshot` | métricas calculadas (código) | `uf`, `as_of`, `window_days`, `metrics` (M1–M4 + proxies), `run_id`, `data_snapshot_sha256` |
| `report` | relatório gerado | `run_id`, `generated_at`, `status` (`ok/degraded`) |
| `summary` | resumo regional/por patógeno (LLM pequeno + judge) | `scope` (região/patógeno), `text`, `evidence_ids[]`, `valid_until` |

`claim.type` (enum fechado): `alert_level`, `case_trend`, `death_trend`, `hospital_pressure`, `vaccination`, `outbreak`, `public_health_measure`, `other`. `direction`: `up | down | stable | unknown`.

### 2.2 Arestas (todas com proveniência)

| Aresta | De → Para | Observações |
|---|---|---|
| `in_region` | `uf → region` | estática |
| `adjacent_to` | `uf → uf` | estática e **simétrica** (par de arestas; teste de simetria) |
| `published_by` | `article → source` | |
| `mentions` | `article → uf` | entidade ligada por dicionário/LLM |
| `about` | `article → pathogen` | |
| `asserts` | `article → claim` | |
| `concerns` | `claim → uf | pathogen` | |
| `has_snapshot` | `uf → snapshot` | |
| `describes` | `report → snapshot` | |
| `cites` | `report → article | claim` | só o que a narrativa realmente usou |
| `summarizes` | `summary → region | pathogen` | |

Campos comuns nas arestas e nós gerados: `created_at`, `run_id`, `produced_by` (`code` ou `tier/modelo/prompt@versão`), `judge` (`passed`, `score`) e `confidence`.

### 2.3 Esquema (esboço — validar sintaxe/índices no spike T7b com as skills `surrealql*` e `surrealdb-vector`)

```surql
DEFINE TABLE OVERWRITE uf SCHEMAFULL;
DEFINE FIELD OVERWRITE code ON uf TYPE string ASSERT $value = /^(BR|[A-Z]{2})$/;
DEFINE TABLE OVERWRITE adjacent_to TYPE RELATION IN uf OUT uf SCHEMAFULL ENFORCED;

DEFINE TABLE OVERWRITE article SCHEMAFULL;
DEFINE FIELD OVERWRITE title ON article TYPE string;
DEFINE FIELD OVERWRITE snippet ON article TYPE string;
DEFINE TABLE OVERWRITE claim SCHEMAFULL;
DEFINE FIELD OVERWRITE type ON claim TYPE string
  ASSERT $value IN ["alert_level","case_trend","death_trend","hospital_pressure",
                    "vaccination","outbreak","public_health_measure","other"];
DEFINE FIELD OVERWRITE confidence ON claim TYPE float ASSERT $value >= 0 AND $value <= 1;

-- Busca textual em pt-BR (BM25); FULLTEXT substitui SEARCH ANALYZER (deprecado na 3.0)
DEFINE ANALYZER OVERWRITE pt_br TOKENIZERS class FILTERS lowercase, ascii, snowball(portuguese);
DEFINE INDEX OVERWRITE article_text ON article FIELDS title, snippet FULLTEXT ANALYZER pt_br BM25;
DEFINE INDEX OVERWRITE claim_text ON claim FIELDS text FULLTEXT ANALYZER pt_br BM25;

-- Opcional (estágio 2): embeddings + HNSW, ligado por flag
-- DEFINE FIELD embedding ON claim TYPE option<array<float>>;
-- DEFINE INDEX claim_vec ON claim FIELDS embedding HNSW DIMENSION <n> DIST COSINE TYPE F32;
```

### 2.4 Seeds versionados
`src/srag_sentinel/kg/seed/` — `ufs.yaml` (27 UFs, nome, região), `adjacency.yaml` (vizinhança), `pathogens.yaml` (ontologia com aliases em pt-BR), `sources.yaml` (domínios/trust; compartilhado com a allowlist do G2). Testes: toda UF tem região e ≥ 1 vizinha, adjacência simétrica, aliases sem colisão entre patógenos.

## 3. Pipeline

### 3.1 Construção (`build_kg`, por relatório, após `collect_news`)
1. **Entrada:** artigos aprovados no G2 (já sanitizados, sem PII; só título + trecho).
2. **Ligação de entidades (barata):** dicionário/regex determinístico sobre `uf` e `pathogen.aliases` — sem LLM.
3. **Extração de afirmações (`kg.extract_claims`):** LLM **pequeno** via router ([08](08-llm-router-judge.md)), saída estruturada (`ClaimDraft[]`: `type`, `text`, `evidence_span`, `uf_codes`, `pathogen_ids`, `direction`). **Validadores determinísticos:** `evidence_span` precisa existir literalmente no texto do artigo; `uf_codes`/`pathogen_ids` ∈ ontologia; `type`/`direction` ∈ enums; no máx. N afirmações por artigo. Juiz conforme a política da tarefa.
4. **Escrita:** funções tipadas de *upsert* (`kg.writer`), idempotentes por id (hash), com proveniência; usuário de banco `kg_writer`. Itens reprovados pelo juiz/validadores **não** entram no grafo (vão para `quarantine`, com motivo, para auditoria).
5. **Snapshot:** o `MetricsPayload` do relatório vira `snapshot` (+ `has_snapshot`); no `finalize`, `report` e `cites`/`describes`.

### 3.2 Recuperação (`retrieve_context`, GraphRAG híbrido)
Entrada: escopo (UF/`BR`), métricas e perguntas-guia **derivadas por código** das métricas (ex.: M1 > 0 → "por que os casos aumentam em {UF}?"; M3 alta → "pressão hospitalar").
1. **Sementes:** `uf` do escopo, patógenos citados, região da UF.
2. **Busca textual BM25** em `article`/`claim` (consulta a partir de entidades+termos fixos; **nunca** SurrealQL gerado por LLM). *Estágio 2 (opcional):* KNN por HNSW com embeddings, mesclado por RRF.
3. **Expansão no grafo** (1–2 saltos, limite de profundidade/fan-out): vizinhas (`adjacent_to`), mesma região, mesmo patógeno, afirmações do mesmo artigo.
4. **Resumos regionais** (`summary`): recuperados do cache; se ausentes/expirados, gerados por LLM pequeno + juiz (spec 08) a partir das afirmações já aceitas da região.
5. **Ranqueamento e corte:** pontuação = relevância (BM25/RRF) × confiança da afirmação × confiança da fonte × recência (decaimento); deduplicação por artigo; top-K (padrão 12).
6. **Saída:** `EvidencePack` com itens `EvidenceItem{evidence_id, kind (article|claim|summary|snapshot), text, score, graph_path, provenance, url?}`.

### 3.3 Uso na síntese
- O LLM de síntese recebe `EvidencePack` **delimitado como dado não confiável** e cita **`evidence_id`** (substitui/estende `article_refs` — [03](03-agent-and-tools.md)).
- **G3** verifica: cada `evidence_id` citado ∈ pacote; cada `evidence_id` de artigo/afirmação mostra `url`/fonte no relatório; **números continuam vindo só das métricas** (afirmações de notícias com números são citadas como "segundo {fonte}", nunca promovidas a métrica).
- Falha de KG/retrieval ⇒ degradação `KG_UNAVAILABLE`: segue com notícias planas (comportamento anterior) e sinaliza.

## 4. Segurança e governança do KG
| Risco | Controle |
|---|---|
| Envenenamento do grafo por notícia maliciosa | G2 antes de tudo; allowlist/`trust` de fonte; piso de confiança; validadores (span literal, ontologia, enums); juiz; quarentena; `expires_at` (padrão 30 dias) |
| Prompt injection na extração | LLM pequeno **sem tools**, saída em schema, texto delimitado como dado; nenhuma string do LLM vira consulta |
| Injeção de SurrealQL | consultas fixas e parametrizadas (templates com limites de salto); ids construídos por código |
| Dado pessoal no grafo | nenhum nó de pessoa; extração só de entidades geográficas/patógenos/afirmações; scrubber de PII em título/trecho antes de gravar |
| Perda de proveniência | `produced_by`/`judge`/`run_id` obrigatórios em nós gerados; eventos de auditoria `kg_write`/`kg_quarantine` ([05](05-governance-audit.md)) |
| Crescimento sem controle | TTL, limite de itens por relatório, rotina `kg prune` |

Usuários do banco `kg`: `kg_writer` (EDITOR, só no processo de construção), `api_ro` (VIEWER). A trilha de auditoria continua no banco `audit`.

## 5. Observabilidade
Spans `kg.extract`, `kg.write`, `kg.retrieve` (atributos: contagens, K, saltos, ids — **sem texto**). Métricas: `srag.kg.nodes_written{kind}`, `srag.kg.quarantined{reason}`, `srag.kg.retrieval.items`, `srag.kg.retrieval.duration`.

## 6. Configuração
`SRAG_KG_ENABLED` (padrão `true`), `SRAG_KG_TOP_K=12`, `SRAG_KG_MAX_HOPS=2`, `SRAG_KG_CLAIM_TTL_DAYS=30`, `SRAG_KG_VECTOR_ENABLED=false` (+ `SRAG_EMBEDDINGS_PROVIDER/MODEL` quando ligado; provedor de embeddings independente do LLM de chat — a Anthropic não oferece embeddings).

## 7. Testes e avaliação
- **Unit:** seeds (simetria, aliases), validadores de afirmação, ranqueamento, montagem de `EvidencePack`.
- **Integração (SurrealDB real):** esquema/índices, `RELATE`, FTS pt-BR (acentos, plural), travessia com limite de salto, idempotência dos upserts, permissões do `kg_writer`/`api_ro`.
- **Corpus de avaliação** (`tests/fixtures/kg/`): ≈ 30 manchetes/trechos rotulados à mão (UF, patógeno, tipo/direção da afirmação) → **F1 de extração**, **recall@K de recuperação** em ≈ 15 perguntas, e *groundedness* (todo `evidence_id` citado existe). Metas iniciais: F1 de entidades ≥ 0,85 (dicionário), F1 de afirmações ≥ 0,70 (tier small + juiz), recall@12 ≥ 0,8.
- **Adversarial:** artigos com injeção/Unicode oculto/spans falsos não geram nós nem arestas.
- **Fail-closed:** LLM pequeno que inventa `evidence_span` ⇒ 0 itens gravados.

## 8. Aceitação
- [ ] `build_kg` + `retrieve_context` rodam ponta a ponta com fakes e no Compose com SurrealDB real.
- [ ] Relatório cita ≥ 1 `evidence_id` com caminho no grafo (`graph_path`) quando houver notícias relevantes.
- [ ] Nenhum nó/aresta sem proveniência; itens reprovados vão para quarentena e para a auditoria.
- [ ] Desligar `SRAG_KG_ENABLED` mantém o relatório funcionando (notícias planas).
