# Implementation Plan: SRAG Sentinel

> Fonte: [SPEC.md](../SPEC.md) (rev. 2, aprovada) e [docs/specs/](../docs/specs/). Lista de tarefas: [tasks/todo.md](todo.md). Skills por stack: [.claude/skills/README.md](../.claude/skills/README.md).

## Overview
PoC de agente (LangGraph) que gera relatório SRAG (HTML + JSON + PDF) combinando 4 métricas determinísticas do Open DATASUS (agregados no SurrealDB) com notícias (Google News RSS → GDELT) e narrativa LLM verificada (4 provedores). O SurrealDB também hospeda um **grafo de conhecimento** usado por um **GraphRAG** (BM25 + travessia), cujas tarefas baratas rodam em **LLMs pequenos** roteados por um **LLM Router + Judge** (cascata com validadores primeiro). Guardrails, auditoria encadeada, OTel e Docker Compose fazem parte do produto, não do acabamento.

> Rev. 3 (2026-11-16): correções da revisão da Fase 1 (ADR 0015), specs 07/08, ADRs 0016–0018 e diagramas Mermaid; novas tarefas **T6b, T6c, T7b, T7c, T10c, T11b**.

## Estratégia
1. **Risco primeiro (Fase 0 ✔, e T7b para o KG):** as incertezas viram spikes curtos antes do código — Python 3.15, colunas/URLs do DATASUS, append-only no SurrealDB, notícias, WeasyPrint e (novo) FTS pt-BR/`RELATE` do grafo.
2. **Fatias verticais:** a primeira fatia entrega *métricas reais de ponta a ponta* (ingestão → SurrealDB → CLI imprime M1–M4); só depois entram LLM, notícias e guardrails. Cada tarefa deixa o sistema funcionando.
3. **Qualidade desde o início:** lint, tipos e testes entram na tarefa 1; TDD para métricas e guardrails.
4. **Diagrama, README e ADRs** são tarefas explícitas (entregáveis do desafio), não sobras.

## Grafo de dependências

```
T0.* spikes ──► T1 scaffold ──► T2 domain/metrics ──┐
                    │                                 ├─► T4 ingest ─► T5 CLI métricas  ══ CP1
                    └─► T3 SurrealDB schema/repo ─────┘
── Núcleo do relatório (notícias planas) ─────────────────────────────────────────────
T1 ─► T6 LLM factory ─► T6b Router ─► T6c Judge ──────────────────────────┐
T1 ─► T7 News (RSS→GDELT) ────────────────┐                               │
T1 ─► T8 G1/G4 ───────────────────────────┼─► T11 grafo LangGraph ─► T12 HTML/JSON ─► T13 PDF ══ CP2
T3 ─► T9 auditoria ───────────────────────┤        ▲
T7 ─► T10 G2 ─────────────────────────────┤        │
T6b,T10 ─► T10b G3 ───────────────────────┘────────┘
── GraphRAG e grafo de conhecimento (Fase 2b) ─────────────────────────────────────────
T3 ─► T7b KG spike+esquema+seeds ─┐
T6c,T7,T7b,T10 ─► T7c build KG ───┴─► T10c retrieve GraphRAG ─► T11b integrar ao grafo ══ CP2b
T11,T6c ────────────────────────────────────────────────────────────────┘
── Serviço, observabilidade e entrega ────────────────────────────────────────────────
T11b,T13 ─► T14 API+CLI report ─► T15 OTel ─► T16 Docker/Compose ─► T17 Grafana ══ CP3
T16 ─► T18 CI │ T11b ─► T19 diagramas (Mermaid → PDF) │ todos ─► T20 corpus adversarial, avaliações, conformidade
T20 ─► T21 README + ADRs ══ CP4 (entrega)
```

Paralelizável (sessões separadas, sem arquivos em comum): T6 ∥ T7 ∥ T8 ∥ **T7b** após T1/T3; T9 ∥ T10 após T3/T7; T6b→T6c ∥ T7b; T17 ∥ T18 ∥ T19 no fim. O resto é sequencial.

**Ordem recomendada na Fase 2:** primeiro o núcleo (T6, T6b, T7, T8, T9, T10, T10b, T11, T12, T13 ⇒ **CP2: relatório completo com notícias planas**), depois a Fase 2b (T6c, T7b, T7c, T10c, T11b ⇒ **CP2b: GraphRAG integrado**). Assim existe uma entrega válida mesmo que o GraphRAG atrase; `SRAG_KG_ENABLED=false` preserva o fluxo do CP2.

## Decisões de planejamento
- Tarefas ≤ 5 arquivos (S/M). Uma tarefa = um commit (Conventional Commits) e um PR curto.
- Resultado de cada spike vira ADR/nota em `docs/adr/` **e** atualização da spec antes de seguir (spec viva).
- Fallback Python 3.14 decidido em T0a; todas as tarefas seguintes usam a versão decidida.
- Nenhuma tarefa de fase 1–2 depende de chave de LLM/rede: tudo com fakes; execução `live` só em T20.

## Riscos e mitigação
| Risco | Impacto | Mitigação / tarefa |
|---|---|---|
| Wheels ausentes no Python 3.15 | Alto | T0a primeiro; fallback 3.14 |
| Colunas/URLs DATASUS diferentes do assumido | Alto | T0b antes do schema e da ingestão |
| Append-only inviável no SurrealDB | Médio | T0c; fallback documentado (hash chain + export) |
| GDELT instável / sem rate-limit documentado | Médio | T0d; cache + degradação em T7 |
| WeasyPrint/Pango na imagem slim | Médio | T0d; teste de PDF no CI |
| Narrativa falha grounding com muita frequência | Médio | T10b com corpus; prompts versionados; retry + degradação |
| Escopo (≈ 28 tarefas) vs. prazo do desafio | Médio | CP1 e CP2 já são entrega mínima válida (métricas + relatório); a Fase 2b (GraphRAG) é isolada por flag; fases 3–4 ordenadas por valor para avaliação |
| FTS pt-BR/`RELATE`/HNSW no SurrealDB v4 diferem do esperado | Médio | T7b é spike antes de T7c/T10c; vetores são opcionais (BM25 + travessia cobrem o estágio 1) |
| Qualidade da extração por LLM pequeno / viés do juiz | Médio | validadores determinísticos primeiro, juiz só em ambiguidade, fixtures rotuladas, metas de F1 e κ; fallback para `large` e `drop_item` |
| Envenenamento do KG via notícia | Alto | G2, `trust` de fonte, validadores, quarentena, TTL, nenhuma consulta gerada por LLM |
| Custo/latência extra de `build_kg` | Médio | cascata `small → large`, limites por relatório (G4), paralelismo limitado; `SRAG_KG_ENABLED=false` |

## Perguntas em aberto
Nenhuma bloqueia o início. As cinco da SPEC §9 são respondidas pelas tarefas T0a–T0d.
