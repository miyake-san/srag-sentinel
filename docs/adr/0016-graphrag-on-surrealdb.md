# ADR 0016 — GraphRAG "leve" sobre o SurrealDB

- Status: aceito (2026-11-16) · Spec: [07](../specs/07-graphrag-knowledge-graph.md)

## Contexto
O SurrealDB foi escolhido (ADR 0003) também para sustentar um **GraphRAG**, não só para guardar os agregados do DATASUS. O sistema já tem notícias (GDELT/RSS) e métricas; falta um jeito de recuperar **evidências relacionadas por geografia, patógeno e fonte**, com proveniência, para a narrativa. O SurrealDB oferece, num único motor, documentos, **arestas (`RELATE`, travessia `->`/`<-`)**, **busca textual BM25 (`FULLTEXT`)** e **vetores (HNSW, KNN)** — conforme as skills oficiais incorporadas ao repositório.

## Opções
| Opção | Prós | Contras |
|---|---|---|
| **A. GraphRAG leve: KG guiado por ontologia + recuperação híbrida (BM25 + travessia) + resumos por região/patógeno estáticos** | usa só o SurrealDB; sem dependência de embeddings; auditável; barato; encaixa no volume da PoC | sem descoberta automática de comunidades |
| B. GraphRAG "completo" estilo Microsoft (extração em todo o corpus + detecção de comunidades Leiden + resumos hierárquicos) | maior cobertura em corpora grandes | indexação cara em LLM, motor/algoritmo adicionais, corpus aqui é pequeno e renovado a cada relatório |
| C. RAG vetorial puro | simples | perde relações (vizinhança, região, patógeno), pior explicabilidade |
| D. Neo4j/outro grafo + vetor separado | ecossistema maduro | segundo banco, contraria a decisão do ADR 0003 |

## Decisão
**Opção A**, em dois estágios:
1. **Estágio 1 (padrão):** BM25 (`FULLTEXT` com analisador pt-BR) + expansão por travessia (1–2 saltos com limite) + resumos regionais/por patógeno cacheados + ranqueamento por relevância × confiança × recência.
2. **Estágio 2 (opcional, flag):** KNN com HNSW sobre embeddings, mesclado por RRF. Fica fora do caminho padrão porque exige um provedor de embeddings (a Anthropic não oferece) e porque BM25 já cobre bem manchetes curtas em português.

"Comunidades" = **estruturas conhecidas** (região, patógeno), não grafos descobertos por algoritmo.

## Consequências
- Nenhuma consulta é gerada por LLM; templates parametrizados com limites de profundidade.
- Dependência de um spike (T7b) para validar: analisador `snowball(portuguese)`, índices `FULLTEXT`, `RELATE`/`TYPE RELATION` e travessias na versão v4.
- Evolução natural: ligar o estágio 2 e, com mais dados, avaliar comunidades automáticas.
