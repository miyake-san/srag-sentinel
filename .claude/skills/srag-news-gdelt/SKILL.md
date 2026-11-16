---
name: srag-news-gdelt
description: Using the GDELT DOC 2.0 API as the default news source for srag-sentinel (query construction for Brazilian Portuguese health news, parameters, caching, degradation) behind the NewsProvider port, plus how G2 treats retrieved articles as untrusted. Use when editing src/srag_sentinel/news or news guardrails.
---

# srag-sentinel · News via GDELT (NewsProvider)

Spec: `docs/specs/03-agent-and-tools.md` §3 and `docs/specs/04-guardrails-security.md` G2.

## API facts (from the GDELT launch post; re-verify in the spike)
- Endpoint: `https://api.gdeltproject.org/api/v2/doc/doc` — `mode=artlist`, `format=json`.
- `maxrecords` default 75, max 250 (we ask ≤ 25). `timespan` units: minutes (min 15), `h`, `d`, `w`, `m`; default window 3 months.
- Query operators go inside the query text: `sourcelang:portuguese`, `sourcecountry:brazil` (or FIPS `BR`), `domain:` / `domainis:`.
- **Spike T0d (ADR 0014):** the service states "one request every 5 seconds" (plain-text 429), answered 429 on ~60 % of calls with 11–19 s latency, sometimes returned `{}`, and gave off-topic results (pet-shop articles) for `influenza`/`srag` queries. Google News RSS (`news.google.com/rss/search?q=…&hl=pt-BR&gl=BR&ceid=BR:pt-419`, operator `when:30d`) answered in ~1 s with 60–100 relevant items; fallback chain proposed, pending user decision. Parse RSS with `defusedxml`.
- Defensive client (limiter ≥ 6 s, one in flight, timeout ≥ 45 s, ≤ 2 queries/report, simple queries, treat 429/non-JSON/`{}`):
- (original note) Rate limits are not documented → defensive client: fixed host, short timeout, retry with backoff on 429/5xx, cache in `app.news_cache` (TTL ~6 h), degrade with `NEWS_UNAVAILABLE`.

## Rules
- Provider returns only metadata + short snippet (title, source/domain, date, URL, snippet ≤ 400 chars). **Do not fetch article pages** in the PoC (SSRF/injection surface).
- Everything returned is untrusted: strip markup and invisible/bidi Unicode, drop injection-looking text, scrub PII, dedupe by canonical URL/title, filter by domain allowlist/score and date window, then wrap in `<untrusted_news id="A#">` for the LLM.
- Queries come from the LLM planner but pass a validator (length, charset, no operators beyond the allowed set) and a template fallback.
- Tests: `respx` fixtures for success, empty, malformed JSON, 429/5xx, timeouts; adversarial titles/snippets.
- Tavily is an optional alternative implementing the same port (needs `TAVILY_API_KEY`).

## References (verified 2026-11-16)
- GDELT DOC 2.0 API — https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
- OWASP LLM Top 10 (prompt injection) — https://genai.owasp.org/llm-top-10/
- OWASP LLM prompt-injection prevention cheat sheet — https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
