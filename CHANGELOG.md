# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it has a first release.

## [Unreleased]

### Added
- **API perimeter** (`api/perimeter.py`, spec 09 A1–A7, ADR 0020): bearer keys (`SRAG_API_KEYS`, required outside
  `dev`; Compose now runs as `prod`), per-key rate limit, concurrency cap, 1 KiB JSON-only body, security headers, CSP
  on the HTML report, counters-only audit route and `srag.api.rejections`. **Breaking for API clients:** send
  `Authorization: Bearer`.
- **Detector normalisation and wider PII scrubbing** (spec 09 §4): injection rules also run on homoglyph-folded,
  letter-joined and leetspeak variants plus a compact-phrase check; the scrubber adds card numbers (Luhn), CEP, RG
  (with the cue) and names after a cue. Base64, French and paraphrase remain undetected by design (ADR 0022).
- **Security validation** (`docs/security-validation.md`), spec 09 (API perimeter, agent and future chat security) and
  ADRs 0020–0022. Finds that the API has no authentication, rate limit or body cap (not yet implemented), that the
  injection detector is a signal rather than a barrier, and fixes spec 04 drift (7 columns, `env.example`).
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
- **LLM layer**: a minimal structured-output port, a lazy provider factory for Anthropic (default), Gemini, NVIDIA NIM
  and OpenRouter with fail-fast validation, a scripted fake model, and the **LLM router** (static `policy.yaml`,
  small→large cascade, error/warning validators, judge port, per-tier call budget and audit events).
- **News**: Google News RSS (defusedxml, no redirects) and GDELT (6 s limiter) providers, a validated query model
  without provider operators, a fallback chain with deduplication and a TTL cache; verified against the real feed.
- **Guardrails**: G1 request validation (specific rule ids, never echoes input), G4 run budget (calls per tier,
  news queries, articles, deadline) and **G2 for news**: hidden-Unicode sanitising, instruction-injection detection
  (Portuguese and English), source trust by domain suffix, topic relevance, date window, an escaped
  `<untrusted_news>` wrapper and a PII scrubber (CPF/CNPJ with check digits, e-mail, Brazilian phones).
- **Audit trail**: hash-chained, append-only `audit` database (record-access writer, `READONLY` fields enforced even
  for administrators, unique `seq`), a per-run recorder with router and guardrail adapters, and
  `srag-sentinel audit verify|export` with an external head anchor to detect tail truncation.
- **G3 narrative grounding**: numbers only from the cited metrics (or the cited article, attributed), existing
  references, M1–M4 coverage, declared proxies and data maturity, content policy, PII, M1 direction and report dates.
- **Agent graph (LangGraph)**: fixed flow `validate → metrics → plan news → collect news → synthesize → verify →
  render → finalize` with one bounded retry carrying the G3 feedback, versioned prompts, per-node audit and
  degradations (`PLAN_FALLBACK`, `NEWS_UNAVAILABLE`, `NARRATIVE_REJECTED`); a lying model yields a metrics-only report.
- **Report rendering**: deterministic accessible SVG charts (daily 30 days with 7-day moving average, monthly 12 months
  with the partial month hatched), a self-contained HTML report (Jinja2 autoescape, no JavaScript, no remote assets,
  strict CSP, http(s)-only source links, proxy badges, limitations and provenance), a versioned `report.json` with the
  artifact hashes, and a PDF rendered from the same HTML by WeasyPrint with a fetcher that refuses every non-`data:`
  URL. A PDF failure degrades the report (`PDF_UNAVAILABLE`) instead of failing it; artifact hashes are audited.
- **Knowledge graph and GraphRAG** (`kg` database on SurrealDB): closed-ontology schema with typed, enforced relations,
  versioned seeds (27 UFs, regions, symmetric borders, pathogens with pt-BR aliases), dictionary entity linking,
  claim extraction by the small model through the router (validators for literal spans, ontology and instructions, then
  the judge), idempotent writes with provenance, quarantine, TTL pruning, regional summaries, retrieval by BM25 plus
  bounded graph expansion with ranking, and `build_kg`/`retrieve_context` graph nodes with the `KG_UNAVAILABLE`
  degradation. The report lists the cited evidence with its graph path and who extracted and judged it.
- **LLM judge**: rubric-based, structured and fail-closed, with Cohen's kappa calibration tooling and a live calibration test.
- ADR 0019 with the SurrealDB findings for the graph.
- **Service**: `ReportService` composition root (least-privilege connection per job), FastAPI routes to create and
  fetch reports (JSON, HTML, PDF) and read a run's audit events, `/healthz` and `/readyz`, RFC 9457 problem documents
  that never echo input, and the `report` and `serve` commands.
- **Observability**: OpenTelemetry traces and `srag.*` metrics over OTLP, fed from the audit recorder so no content can
  leak into attributes, plus JSON logs carrying the trace id.
- **Deployment**: multi-stage non-root Dockerfile with a read-only filesystem and the WeasyPrint libraries, a Compose
  stack (SurrealDB without a published port, API, init and ingest jobs, collector, Jaeger, Prometheus, Grafana) on
  separate networks, provisioned Grafana dashboard, example alerts, GitHub Actions CI and the architecture-diagram PDF.
- 405 automated tests (unit, property-based, adversarial and integration against a real SurrealDB), ruff and strict
  mypy clean. The real-PDF smoke test is skipped on hosts without the Pango libraries.

- **Documentation and evaluation**: full README (architecture, quickstart, metrics and proxies, guardrails, LGPD,
  audit, limitations and model card), ADRs 0001–0011, `docs/evaluation.md` (what was measured and what was not),
  `docs/provider-conformance.md`, an end-to-end script for the Compose stack and the `kg prune` command.
- **Adversarial corpus**: 35 prompt-injection payloads checked against the news filter, the knowledge-graph build and
  the judge prompt, plus hostile request parameters and a false-positive check on real headlines.

- **More LLM providers and priority failover**: Groq, Unsloth (any OpenAI-compatible server) and Ollama join
  OpenRouter, NVIDIA NIM, Gemini and Anthropic, and the large tier accepts an ordered list
  (`SRAG_LLM_PRIORITY`, default order OpenRouter, Groq, NVIDIA NIM, Unsloth, Gemini, Ollama) that fails over to the
  next provider and skips the ones that are not configured. Not yet exercised against a real service.

- **Usage guide, architecture overview and impact report**: `docs/usage-guide.md` (examples for CLI, API, providers and
  audit), `docs/architecture-overview.md` (every component with its ADRs, specs and tests), `docs/impact.md` (what was
  measured, how, and a critical review) and `scripts/measure_impact.py`. The company in the brief is now stated to be
  fictitious.

### Changed
- Python target is **3.14** rather than 3.15: `zstandard` and `pyyaml` have no cp315 wheels (ADR 0008).
- News source is a **chain**: Google News RSS (primary), GDELT (secondary), Tavily (optional) after GDELT proved
  rate-limited and off-topic in the spike (ADR 0014).
- `as_of` now defaults to the latest day **minus 3 settle days** and the excluded days are stated in the output
  (ADR 0015).

### Fixed
- The CI image scan (Trivy, CRITICAL and HIGH) failed on `zlib1g` and on the base image's `pip`/`setuptools`
  (with vendored `urllib3` and `msgpack`). The runtime image now upgrades system packages and removes `pip`; the
  rescan reports 0 findings and the PDF smoke test still passes.
- The image scan still failed after that: Trivy's secret scanner flagged text inside the installed Anthropic SDK
  (11 "GCP service account" false positives). The scan now covers vulnerabilities only (0 findings on the rebuilt
  image with the latest database); repository secrets stay covered by gitleaks.
- The architecture PDF showed empty boxes on 5 of 6 pages (WeasyPrint ignores Mermaid's HTML labels); labels are
  now SVG text in a pinned font, in dark text.
- `aquasecurity/trivy-action` bumped from 0.28.0 to 0.35.0 (Dependabot alert, affected versions < 0.35.0).
- API route tests no longer depend on the developer's `.env` (they build their own settings).
- The news filter missed 13 of 35 injection payloads (role-play, grade manipulation, requests to leak instructions,
  text addressed to the model); its rules now cover them.
- The Docker reports volume was owned by root, so the non-root service could not store reports.
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
