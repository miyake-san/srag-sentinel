# ADR 0019 — Achados do spike do KG no SurrealDB (T7b)

- Status: aceito (2026-11-16) · Spec: [07](../specs/07-graphrag-knowledge-graph.md) · Spike: `spikes/t7b_kg_surreal.py`

## Contexto
Antes de fixar o esquema do grafo, validamos no SurrealDB v4.0.1 (SDK Python 3.0.0) a busca textual em pt-BR, as relações tipadas, as travessias e as permissões.

## Achados e decisões
1. **`FULLTEXT` indexa uma única coluna.** `FIELDS title, snippet` falha ("Expected one column"). Decisão: o artigo tem um campo `text` (título + trecho) e o índice cobre só ele.
2. **Sintaxe de relação:** `TYPE RELATION IN a OUT b ENFORCED SCHEMAFULL` (`ENFORCED` vem antes de `SCHEMAFULL`). Com `ENFORCED`, `RELATE` entre tipos errados **lança erro** (não retorna vazio), então o esquema fecha a ontologia.
3. **`DEFINE FIELD` aceita uma tabela por vez**; os campos de proveniência das 11 arestas são declarados um a um.
4. **Analisador `pt_br`** (`class`; `lowercase, ascii, snowball(portuguese)`): acentos e plural funcionam (`internações`/`internacoes`, `respiratória`/`respiratorias`, `casos`/`caso`, `aumentam`/`aumento`). Consulta com vários termos exige **todos** (AND, escores somados): um termo sem correspondência zera o resultado; por isso a recuperação faz **uma consulta por termo** e soma os escores no código. **Lacunas do stemmer:** `internacao` ≠ `internacoes`, `vacina` ≠ `vacinação`, `hospital` ≠ `hospitais`. Decisão: a recuperação expande cada termo com um léxico de variantes (`kg/lexicon.py`) em vez de depender só do stemmer.
5. **Travessias** `->adjacent_to->uf->adjacent_to->uf` funcionam, mas retornam a UF de origem e duplicatas: o código remove a origem e deduplica; profundidade máxima é fixa no template (≤ 2 saltos por padrão).
6. **Permissões:** EDITOR escreve e VIEWER lê; a escrita do VIEWER retorna vazio (não lança). O banco `kg` tem `kg_writer` (EDITOR) e `api_ro` (VIEWER).
7. **Idempotência de arestas:** `INSERT RELATION ... ON DUPLICATE KEY UPDATE` com id determinístico (ex.: `adjacent_to:SP_RJ`), pois `RELATE` simples cria uma nova aresta a cada execução. `run_id` ausente é `NONE` (campo `option<string>`).

## Consequências
- `db init` cria o banco `kg`, aplica `kg/schema/kg.surql`, semeia UFs/regiões/patógenos/adjacência e define os usuários; exige `SRAG_SURREAL_KG_WRITER_PASSWORD`.
- Vetores (HNSW) continuam opcionais e fora desta entrega.
