# Avaliação: o que foi medido e o que não foi

Números produzidos nos testes deste repositório (2026-11-17). Onde o dado depende de um LLM real, está dito.

## Medido
| Item | Resultado | Como |
|---|---|---|
| Ligação de entidades (UF e patógeno, por dicionário) | precisão 1,00 · recall 1,00 · F1 1,00 em 30 manchetes | `tests/unit/kg/test_kg_entities_and_extraction.py` |
| Recuperação do GraphRAG | recall@12 médio **0,978** (mínimo 0,67) em 15 perguntas | `tests/integration/test_kg_retrieve.py`, SurrealDB real |
| Falsos positivos do G2 | 0 em 30 manchetes reais | `tests/guardrails/test_adversarial_corpus.py` |
| Detecção de injeção (G2) | 35 de 35 payloads PT/EN, em título e em trecho | idem |
| Envenenamento do KG | 0 afirmações gravadas para os 35 payloads, mesmo com um modelo que obedece | idem |
| Parâmetros hostis (G1) | 10 de 10 rejeitados sem repetir a entrada | idem |
| Suíte completa | 508+ testes, incluindo integração contra SurrealDB real e execução no contêiner | CI/local |

**Cuidado ao ler os números.** O corpus de 30 manchetes foi escrito por mim e os aliases do dicionário foram desenhados junto com ele: o F1 de entidades de 1,00 mostra que o código faz o que foi especificado, **não** que generaliza para manchetes novas. O recall@12 é facilitado pelo tamanho do corpus (12 itens são 40% dele). O corpus adversarial também foi escrito depois de conhecer as regras e levou à correção de 13 lacunas (de 35 payloads) no G2 (papéis, pedidos de nota, vazamento de instruções), o que mostra que a primeira versão das regras era incompleta; é provável que existam outras.

## Não medido (precisa de chave de LLM)
| Item | Meta da spec | Estado |
|---|---|---|
| F1 de afirmações (modelo pequeno + juiz) | ≥ 0,70 | os testes usam um extrator oráculo (F1 trivialmente 1,0): **não há medida** |
| Concordância juiz × rótulo (κ de Cohen) | ≥ 0,6 | **medido em 2026-11-17 (Groq): κ = 0,59, acurácia 0,80, 54 casos, 0 falsos aceites, 11 falsos rejeites. Abaixo da meta por 0,01.** O erro está no lado seguro (o juiz nunca aprovou o que devia rejeitar; rejeitou 11 casos válidos). Os rótulos vêm de perturbações sintéticas do corpus e não tiveram revisão humana, então o κ mede concordância com rótulos escritos por mim, não com um analista |
| Taxa de resolução no tier `small` | ≥ 70% | não medida |
| Custo por relatório vs. "tudo no large" | ≤ baseline | não medido (sem telemetria de tokens/custo) |
| Latência p95 do relatório | ≤ 90 s | não medida com modelos reais |
| Qualidade da narrativa | revisão humana | não avaliada |

## Primeira execução real de ponta a ponta (2026-11-17, Groq, escopo BR)
Dados reais (585.334 linhas ingeridas), notícias reais e modelos reais (grande: `openai/gpt-oss-120b`; pequeno: `openai/gpt-oss-20b`). Resultado: **relatório degradado**, com métricas, gráficos e notícias, mas **sem narrativa** (`NARRATIVE_REJECTED`) e sem PDF (`PDF_UNAVAILABLE`, falta Pango neste Windows; no contêiner o PDF é gerado).

- **Defeito encontrado e corrigido:** a extração de afirmações do grafo escalava respostas inválidas do modelo pequeno para o grande e gastava as 3 chamadas grandes do G4, deixando a síntese sem orçamento (`task_exhausted: budget`). Agora a extração enxerga o orçamento com 2 chamadas grandes reservadas à narrativa e ao seu único retry (`CallBudget.holding_back`).
- **Com a síntese executando, o G3 rejeitou a narrativa duas vezes:** na 1ª tentativa 4 violações (`numeric_grounding` no resumo, num comentário de métrica e numa nota de contexto; `limitations`); na 2ª, 1 violação (`numeric_grounding` em `news_context[0]`). O sistema **falhou fechado**, como projetado: nenhum texto não verificado foi publicado. O modelo, portanto, ainda cita números que não estão nas métricas nem no artigo citado. A auditoria registra o local, não o texto, então a causa exata do número não está nos logs.
- **O que isso mede:** o G3 funciona contra um modelo real; a taxa de narrativas aceitas com esse modelo é, por ora, **0 de 1 execução**. Não há medida estatística.

## Próximos passos
1. Rodar `tests/live` nos demais provedores e registrar em [`provider-conformance.md`](provider-conformance.md) (Groq já foi medido).
2. Investigar os 11 falsos rejeites do juiz (prompt ou rubrica) e repetir; revisão humana dos rótulos; medir o F1 de afirmações com o modelo pequeno.
3. Ampliar o corpus com manchetes reais coletadas (não escritas à mão).
