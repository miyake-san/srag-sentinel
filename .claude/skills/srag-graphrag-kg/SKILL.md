---
name: srag-graphrag-kg
description: Conventions for the srag-sentinel knowledge graph and GraphRAG on SurrealDB — closed ontology, RELATE edges with provenance, claim extraction with deterministic validators, BM25 + graph-traversal retrieval into an EvidencePack, KG poisoning controls. Use when editing src/srag_sentinel/kg, the `kg` database schema, build_kg/retrieve_context nodes or evidence citation in the narrative. Use with the vendored surrealql, surrealql-performance and surrealdb-vector skills.
---

# srag-sentinel · GraphRAG and knowledge graph

Specs: `docs/specs/07-graphrag-knowledge-graph.md`; ADRs 0016 (GraphRAG) and 0017 (model). Router/judge for the small-LLM tasks: skill `srag-llm-router-judge`.

## Rules
- **Closed ontology.** Node tables `uf, region, pathogen, source, article, claim, snapshot, report, summary`; edge tables via `RELATE` (`TYPE RELATION`). Seeds (UFs, regions, adjacency, pathogens with pt-BR aliases, sources) live in versioned YAML; tests: adjacency symmetric, every UF has a region and a neighbour, no alias collisions.
- **Entities by dictionary first**, LLM second. The LLM only extracts claims (`type`/`direction` from fixed enums, `evidence_span` copied literally from the text). Validators reject spans not found in the source, entities outside the ontology, bad enums.
- **Provenance is mandatory** on generated nodes/edges: `run_id`, `produced_by` (`tier/model/prompt@version` or `code`), `judge`, `confidence`, `expires_at` (TTL 30 days). Rejected items go to quarantine + audit (`kg_quarantine`), never to the graph.
- **No LLM-generated queries.** Retrieval uses fixed, parameterised SurrealQL templates with depth/fan-out caps. Ids are built in code (hash of canonical URL), never from model output.
- **Retrieval:** BM25 (`FULLTEXT` with a pt-BR analyzer; verify analyzer/filters in the T7b spike) + 1–2 hop expansion (adjacent UFs, same region, same pathogen) + cached regional summaries → rank by relevance × claim confidence × source trust × recency → `EvidencePack` (`evidence_id`, `graph_path`, provenance). Vector search (HNSW) is an optional stage behind `SRAG_KG_VECTOR_ENABLED`.
- **Numbers come only from metrics.** News claims with numbers are cited as "segundo {fonte}"; G3 checks that every cited `evidence_id` exists in the pack.
- **Privacy:** no person nodes, no full article text (title + short snippet only), PII scrub before writing.
- **Degrade, don't crash:** KG failure ⇒ `KG_UNAVAILABLE` and fall back to flat news.
- Test with a real SurrealDB container for schema/FTS/traversal; use a hand-labelled fixture set (≈ 30 headlines, ≈ 15 questions) for extraction F1 and recall@K; add adversarial articles (injection, hidden Unicode, fake spans) that must create no nodes.

## References
- SurrealDB graph and `RELATE`, full-text, vector search: vendored `surrealql`, `surrealql-performance`, `surrealdb-vector` skills; https://surrealdb.com/docs
- Microsoft GraphRAG (for context on the heavier alternative) — https://microsoft.github.io/graphrag/
