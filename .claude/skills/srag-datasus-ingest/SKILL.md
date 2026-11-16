---
name: srag-datasus-ingest
description: Ingesting the Open DATASUS SRAG dataset in srag-sentinel — locating Parquet resources via the portal's CKAN API, validating against the data dictionary, reading only allowlisted columns with Polars, aggregating per day/UF and upserting into SurrealDB, with manifest hashing. Use when editing src/srag_sentinel/data or the ingest CLI.
---

# srag-sentinel · DATASUS ingestion

Spec: `docs/specs/02-data-and-metrics.md` (§1 source, §2 ingestion + model, §3 allowlist, §4 cleaning).

## Facts (verified 2026-11-16)
- Dataset: "Banco de dados da SRAG — 2019 a 2026", `https://dadosabertos.saude.gov.br/dataset/srag-2019-a-2026`; weekly updates; CC BY-ND 3.0. The old `opendatasus.saude.gov.br/dataset/srag-2021-a-2024` URL redirects to the new portal.
- Resources per year in CSV, JSON, Parquet and XML; data dictionary 2019–2025 is resource `3135ac9c-2019-4989-a893-2ed50ebd8e68`.
- The CKAN API returns 404 on this portal (spike T0b, ADR 0012). Files are public S3 objects named `INFLUD<yy>-<dd>-<mm>-<yyyy>.parquet` under `https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/<year>/`; the name changes every weekly update. Resolve the current URL by reading the resource page's "Baixar" link (regex restricted to that S3 prefix; resource IDs per year in config) and keep a `--url` override.
- Each yearly file is keyed by the epidemiological year of symptom onset and also holds late notifications; ingest the `as_of` year and the previous one.
- Category columns are strings (`"1"`, `"2"`, `"3"`, `"9"`) with `null` — treat `null` as ignored. Read remotely with Polars `scan_parquet(url).select(allowlist)`; do not download whole files.

## Rules
- Prefer Parquet; project **only** allowlisted columns at read time (Polars `scan_parquet(...).select(...)`), so identifying columns are never materialized.
- Validate expected columns/dtypes first and fail loudly if the layout changed; column names in the spec come from the SIVEP-Gripe layout and must be confirmed against the dictionary.
- Map out-of-domain category codes to "ignored" (9); exclude "ignored" from rate denominators; count every dropped/mapped row in the manifest.
- Aggregate to `srag_daily` (uf × day) counters; upsert with deterministic ids so reruns are idempotent; compute `data_snapshot_sha256` over canonical aggregates.
- Never log, trace, or store individual rows. Do not redistribute raw data (license is "no derivatives"); `data/raw` is gitignored and removed after ingest.
- Network: retries with backoff, streaming download, SHA-256 of raw files recorded in the manifest.

## References (verified 2026-11-16)
- Dataset page — https://dadosabertos.saude.gov.br/dataset/srag-2019-a-2026
- CKAN API — https://docs.ckan.org/en/latest/api/
- Polars — https://docs.pola.rs/
- LGPD (Lei 13.709/2018) — https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm
