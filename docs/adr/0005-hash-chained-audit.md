# ADR 0005 — Trilha de auditoria encadeada por hash, só de acréscimo

- Status: aceito · Spec: [05](../specs/05-governance-audit.md) · Achados: [0013](0013-surrealdb-findings.md)

## Contexto
É preciso provar o que o sistema fez em cada relatório e detectar adulteração, sem guardar conteúdo sensível.

## Decisão
Cadeia global no banco `audit`: cada evento tem `seq` único, `prev_hash` e `hash` sobre uma forma canônica. Conteúdo entra **só como hash**; detalhes são escalares sem float. O escritor é um usuário de **record access** (cria e lê, não altera nem apaga), com campos `READONLY` e `UNIQUE(seq)`. Falha ao gravar **aborta a execução**. `audit verify` recomputa a cadeia e aceita uma **âncora externa** (`--expected-head`) para detectar truncamento do rabo; `audit export` gera JSONL.

## Alternativas descartadas
- Log em arquivo: fácil de reescrever.
- Blockchain/ledger externo: custo sem ganho para a PoC.

## Consequências
Adulteração no meio é detectada; truncar o fim só é detectável com a âncora guardada fora do banco, então o README manda registrá-la.
