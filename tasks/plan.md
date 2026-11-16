# Implementation Plan: SRAG Sentinel

> Fonte: [SPEC.md](../SPEC.md) (rev. 2, aprovada) e [docs/specs/](../docs/specs/). Lista de tarefas: [tasks/todo.md](todo.md). Skills por stack: [.claude/skills/README.md](../.claude/skills/README.md).

## Overview
PoC de agente (LangGraph) que gera relatório SRAG (HTML + JSON + PDF) combinando 4 métricas determinísticas do Open DATASUS (agregados no SurrealDB) com notícias (GDELT) e narrativa LLM verificada (4 provedores). Guardrails, auditoria encadeada, OTel e Docker Compose fazem parte do produto, não do acabamento.

## Estratégia
1. **Risco primeiro (Fase 0):** cinco incertezas da spec viram spikes curtos antes de qualquer código de produção — compatibilidade Python 3.15, colunas/URLs do DATASUS, append-only no SurrealDB, GDELT, WeasyPrint.
2. **Fatias verticais:** a primeira fatia entrega *métricas reais de ponta a ponta* (ingestão → SurrealDB → CLI imprime M1–M4); só depois entram LLM, notícias e guardrails. Cada tarefa deixa o sistema funcionando.
3. **Qualidade desde o início:** lint, tipos e testes entram na tarefa 1; TDD para métricas e guardrails.
4. **Diagrama, README e ADRs** são tarefas explícitas (entregáveis do desafio), não sobras.

## Grafo de dependências

```
T0.* spikes ──► T1 scaffold ──► T2 domain/metrics ──┐
                    │                                 ├─► T4 ingest ─► T5 CLI métricas  ══ CP1
                    └─► T3 SurrealDB schema/repo ─────┘
T1 ─► T6 LLM factory ─┐
T1 ─► T7 GDELT ───────┤
T1 ─► T8 G1/G4 ───────┼─► T11 grafo LangGraph ─► T12 render HTML/JSON ─► T13 PDF ══ CP2
T3 ─► T9 auditoria ───┤        ▲
T7 ─► T10 G2 ─────────┤        │
T6,T10 ─► T10b G3 ────┘────────┘
T11,T13 ─► T14 API+CLI report ─► T15 OTel ─► T16 Docker/Compose ─► T17 Grafana ══ CP3
T16 ─► T18 CI │ T11 ─► T19 diagrama PDF │ todos ─► T20 corpus adversarial + conformidade LLM
T20 ─► T21 README + ADRs ══ CP4 (entrega)
```

Paralelizável (sessões separadas, sem arquivos em comum): T6 ∥ T7 ∥ T8 após T1; T9 ∥ T10 após T3/T7; T17 ∥ T18 ∥ T19 no fim. O resto é sequencial.

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
| Escopo (≈ 22 tarefas) vs. prazo do desafio | Médio | CP1 e CP2 já são entrega mínima válida (métricas + relatório); fases 3–4 são ordenadas por valor para avaliação |

## Perguntas em aberto
Nenhuma bloqueia o início. As cinco da SPEC §9 são respondidas pelas tarefas T0a–T0d.
