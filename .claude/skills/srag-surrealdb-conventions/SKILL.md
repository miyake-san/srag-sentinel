---
name: srag-surrealdb-conventions
description: Project-specific SurrealDB conventions for srag-sentinel — namespace/database layout (data, audit, app), role users, versioned .surql schema, parameterized queries, append-only audit table, idempotent upserts. Use together with the vendored surrealql, surrealql-performance, surrealql-functions, surrealdb-python and surrealdb-cli skills whenever touching db/schema, the repository adapter, ingestion writes or the audit store.
---

# srag-sentinel · SurrealDB conventions

Vendored upstream skills give language/SDK/CLI knowledge (`surrealql`, `surrealql-performance`, `surrealql-functions`, `surrealdb-python`, `surrealdb-cli`). This skill only adds **project decisions** (spec: `docs/specs/02-data-and-metrics.md` §2.2, `docs/specs/05-governance-audit.md`).

## Layout
- Namespace `srag`; databases `data` (`srag_daily`, `ingest_manifest`), `audit` (`audit_event`), `app` (`report`, `news_cache`).
- Schema lives in `db/schema/*.surql` (SCHEMAFULL tables, typed fields, indexes, users, permissions), applied idempotently by `srag-sentinel db init`. No schema changes outside these files.
- Role users: `ingest` (write `data`), `api_ro` (read `data`), `api_rw` (`app`), `audit_writer`/`audit_reader`. Root is bootstrap-only.

## Rules
- Run the client in **remote server mode** (WebSocket) with the async SDK; embedded mode is not used.
- **Always** pass values as query variables (`$uf`, `$start`, `$end`); never build SurrealQL with string formatting. Metric queries are fixed templates owned by the repository adapter.
- Deterministic record ids (`srag_daily:[uf, day]`) + upsert ⇒ idempotent ingestion. Use range-friendly ids and the indexes recommended by `surrealql-performance`; verify with `EXPLAIN`.
- Audit (validated in spike T0c, ADR 0013): unique index on `seq`, `READONLY` fields, hash chain, and table `PERMISSIONS FOR select FULL FOR create WHERE $access = 'audit_writer' FOR update, delete NONE`. The app signs in as the **record-access** `audit_writer` (`signin({"namespace","database","access","variables"})`); never give it an EDITOR/OWNER system user (they can DELETE despite `NONE`). A VIEWER can CREATE if the table says `create FULL` — always gate with `$access`.
- **Denied writes do not raise**: SurrealDB returns an empty result (`[[]]`). Always check that the expected record came back; in tests assert final state via an admin connection. A duplicate unique key raises `ValidationError`.
- SDK usage that works (3.0.0): `db = AsyncSurreal(url)`; `await db.signin({...})`; `await db.use(ns, database)`; `res = await db.query(sql, vars)`; `res.execute()` → list of per-statement results; `UPSERT table:[$a, $b] SET …` for idempotent writes.
- Check SDK/server compatibility (SDK 3.0.0 vs server v4.0.1 at spec time) with an integration test against the container; the vendored `surrealdb-python` skill is written for an earlier SDK iteration, so verify examples against the installed version.
- The `curl … | sh` installer line in `surrealdb-cli` is reference text only — we run SurrealDB from the pinned Docker image.

## References (verified 2026-11-16)
- SurrealDB docs — https://surrealdb.com/docs
- DEFINE TABLE (permissions, schemafull) — https://surrealdb.com/docs/surrealql/statements/define/table
- DEFINE ACCESS (record users) — https://surrealdb.com/docs/surrealql/statements/define/access
- Running with Docker — https://surrealdb.com/docs/surrealdb/installation/running/docker
- Upstream skills (MIT) — https://github.com/surrealdb/agent-skills
