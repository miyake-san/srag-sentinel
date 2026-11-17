# ADR 0003 — SurrealDB como banco único (dados, auditoria, grafo)

- Status: aceito · Achados: [0013](0013-surrealdb-findings.md), [0019](0019-surrealdb-kg-findings.md)

## Contexto
O sistema guarda agregados, uma trilha de auditoria que não pode ser reescrita, notícias/afirmações em um grafo e busca textual. Foi decisão do projeto usar o SurrealDB, também para o GraphRAG.

## Decisão
Um servidor SurrealDB (v4.0.1, modo remoto por WebSocket) com **bancos lógicos separados**: `data`, `app`, `audit` e `kg`. Papéis mínimos por banco (ingest, api_ro, api_rw, audit_writer por record access, audit_reader, kg_writer); `root` só no bootstrap. O esquema vive em arquivos `.surql` versionados e `db init` é idempotente. Valores sempre como variáveis ligadas; identificadores vêm de configuração validada.

## Alternativas descartadas
- PostgreSQL + extensões (pgvector/AGE) ou Neo4j + banco relacional: dois sistemas para operar e proteger.
- SQLite: sem papéis por banco nem grafo nativo.

## Consequências
Um sistema só para operar, com permissões por banco. Ressalvas aprendidas: negações de permissão devolvem resultado vazio (toda escrita é conferida), `EDITOR`/root ainda podem apagar (por isso a aplicação nunca recebe essas credenciais para auditoria) e o índice de texto cobre uma coluna.
