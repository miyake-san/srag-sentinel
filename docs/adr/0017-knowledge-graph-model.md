# ADR 0017 — Modelo do grafo de conhecimento

- Status: aceito (2026-11-16) · Spec: [07 §2](../specs/07-graphrag-knowledge-graph.md)

## Contexto
O KG precisa explicar o relatório, ser **seguro** (as notícias são dado não confiável) e **auditável**, sem guardar dado pessoal e sem virar um segundo banco de métricas.

## Decisão
1. **Ontologia fechada e pequena**, em seeds versionados: `uf`, `region`, `pathogen`, `source` (estáticos/derivados) + `article`, `claim`, `snapshot`, `report`, `summary` (gerados). Arestas: `in_region`, `adjacent_to` (simétrica), `published_by`, `mentions`, `about`, `asserts`, `concerns`, `has_snapshot`, `describes`, `cites`, `summarizes`.
2. **Afirmações (`claim`) são nós de primeira classe**, com `type` e `direction` em enums fechados, `evidence_span` literal do texto, `confidence`, `expires_at` (TTL 30 dias) e `produced_by`/`judge` — separam "o que a notícia disse" de "o que o sistema mediu".
3. **Métricas nunca viram afirmações:** o `snapshot` guarda as métricas calculadas por código; números de notícias são citados como tal e jamais promovidos a métrica.
4. **Entidades ligadas por dicionário primeiro** (determinístico); o LLM pequeno só extrai afirmações e ajuda em casos ambíguos, sempre dentro da ontologia.
5. **Proveniência obrigatória** em nós/arestas gerados; itens reprovados vão para quarentena e auditoria, não para o grafo.
6. **Sem nós de pessoa** e sem texto integral de artigos (só título e trecho curtos), reduzindo risco de direitos autorais e de PII.
7. Banco lógico **`kg` separado** (`kg_writer` escreve; `api_ro` lê), distinto de `data` (agregados), `audit` e `app`.

## Alternativas descartadas
- Esquema aberto/gerado pelo LLM (tipos de nó e aresta livres): difícil de validar e fácil de envenenar.
- Guardar as métricas só como propriedade de `uf`: perde histórico entre relatórios; `snapshot` resolve.
- Texto integral dos artigos no grafo: risco de direitos e de injeção maior, sem ganho para manchetes.

## Consequências
- Mudar a ontologia = nova versão dos seeds + migração do esquema (`db init` idempotente).
- A qualidade depende da extração de afirmações; por isso a spec 08 define validadores + juiz + metas de F1 em fixtures.
