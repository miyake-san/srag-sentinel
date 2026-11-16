# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it has a first release.

## [Unreleased]

### Added
- **Specifications** (Portuguese): `SPEC.md` and detailed specs `docs/specs/01`–`08` covering architecture, data and
  metrics, agent and tools, guardrails and security, governance and audit, observability and deployment,
  **GraphRAG with a knowledge graph on SurrealDB** (07) and the **LLM Router and LLM Judge** (08).
- **Architecture diagrams in Mermaid** (`docs/architecture/architecture.md`): system overview, LangGraph flow with
  GraphRAG, router/judge cascade, knowledge-graph model, ingestion and deployment. All six render with
  `mermaid-cli`; the deliverable PDF will be generated from this file.
- **ADRs** `docs/adr/0008`, `0012`–`0018`: Python 3.14 decision, OpenDATASUS findings, SurrealDB findings
  (append-only audit design), news-source and PDF findings, settle days and partial-ingest guard, GraphRAG on
  SurrealDB, knowledge-graph model, and the simplest LLM router/judge approach.
- **Implementation plan** (`tasks/plan.md`, `tasks/todo.md`): phases, dependency graph, checkpoints, risks; extended
  with tasks T6b, T6c, T7b, T7c, T10c and T11b for the router/judge and GraphRAG.
- **Project skills** in `.claude/skills/`: vendored official SurrealDB (including `surrealdb-vector`), LangChain,
  Astral (`uv`, `ruff`) and OpenTelemetry Python skills with licenses and provenance, plus project skills for
  LangGraph, LLM providers, FastAPI/Pydantic, Docker/observability, testing, reporting, news, DATASUS ingestion,
  SurrealDB conventions, guardrails, GraphRAG/KG and the router/judge.
- **Phase 0 spikes** (`spikes/`): dependency compatibility, dataset profiling, SurrealDB roles and append-only audit,
  GDELT, Google News RSS and WeasyPrint.
- **Project scaffold**: `uv` project on Python 3.14, ruff, strict mypy, pytest (`unit`/`integration`/`live` markers),
  `pydantic-settings` configuration with `SRAG_*` variables, CLI entry point `srag-sentinel`.
- **Domain**: SRAG counters, inclusive time windows, metrics M1 case growth, M2 mortality, M3 ICU use (proxy),
  M4 vaccination for COVID-19 and influenza (proxy), completeness and maturity caveats, daily 30-day series with a
  7-day moving average and monthly 12-month series with a partial current month.
- **SurrealDB layer**: versioned `.surql` schema packaged with the app, idempotent `srag-sentinel db init` creating
  namespace, databases and role users, async client helpers, read and write repositories using bound variables only,
  development `compose.yaml` with a health-checked SurrealDB v4.0.1 and a localhost-only dev override.
- **Ingestion**: `srag-sentinel ingest` discovers the current yearly Parquet from the portal's resource page, reads
  only seven allowlisted columns remotely with Polars, cleans and aggregates to daily per-UF counters, merges yearly
  files, upserts idempotently and records a manifest with a snapshot hash. Verified on the real 2025 and 2026 files
  (585,334 rows).
- **Metric tools and CLI**: `get_srag_metrics` and `get_srag_series` with strict argument validation, and
  `srag-sentinel metrics` printing the metrics and both series.
- 121 automated tests (unit, property-based and integration against a real SurrealDB), ruff and strict mypy clean.

### Changed
- Python target is **3.14** rather than 3.15: `zstandard` and `pyyaml` have no cp315 wheels (ADR 0008).
- News source is a **chain**: Google News RSS (primary), GDELT (secondary), Tavily (optional) after GDELT proved
  rate-limited and off-topic in the spike (ADR 0014).
- `as_of` now defaults to the latest day **minus 3 settle days** and the excluded days are stated in the output
  (ADR 0015).

### Fixed
- Case growth (M1) was biased downwards by the incomplete newest days: on real data it moves from −15.6% to −8.8%,
  and the mortality completeness rises from 49.8% to 53.6%.
- `ingest` now refuses a single yearly file, which would overwrite days split across files with partial counts;
  `--allow-partial` accepts the risk explicitly.

### Security
- Only an allowlist of seven columns is ever read from the source; identifying columns never leave the remote file.
- Only daily per-UF aggregates are stored; no patient-level rows reach the database, logs or traces.
- Database users are role-scoped: a read-only user for the API (verified by tests) and a writer used only by the
  ingestion job; identifiers are validated and values are always passed as bound variables.
- Vendored third-party skills were reviewed; skills that pre-authorize `curl`/`ssh` were deliberately not included.
