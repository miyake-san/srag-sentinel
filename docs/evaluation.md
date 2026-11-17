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

## Próximos passos
1. Rodar `tests/live` nos demais provedores e registrar em [`provider-conformance.md`](provider-conformance.md) (Groq já foi medido).
2. Investigar os 11 falsos rejeites do juiz (prompt ou rubrica) e repetir; revisão humana dos rótulos; medir o F1 de afirmações com o modelo pequeno.
3. Ampliar o corpus com manchetes reais coletadas (não escritas à mão).
