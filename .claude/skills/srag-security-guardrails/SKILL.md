---
name: srag-security-guardrails
description: Implementation guide for srag-sentinel guardrails (G1 input, G2 untrusted news, G3 narrative grounding, G4 budget), PII handling, and the audit trail. Use when writing or reviewing anything in src/srag_sentinel/guardrails, governance, or prompts.
---

# srag-sentinel · Guardrails, PII and audit

Spec: `docs/specs/04-guardrails-security.md` and `docs/specs/05-governance-audit.md`. Pair with the global `security-and-hardening` skill if available.

## Rules
- A guardrail is a pure function returning a verdict `{action: allow|sanitize|block, rule_id, details}`. Every verdict is written to the audit trail and counted in OTel (`srag.guardrail.verdicts`).
- **G3 is deterministic**: extract numbers/percentages/dates/URLs from the narrative and match them to the metrics payload and retrieved articles; anything unmatched is a violation. One retry with violation feedback, then fail closed (metrics + charts only).
- **Separation of privileges**: LLM nodes have no tools, files or network; news text is wrapped as untrusted data and never concatenated into system instructions.
- **PII**: allowlisted columns only; aggregates only downstream; scrub CPF/CNPJ/e-mail/phone in news snippets and LLM output; log hashes/ids/counts, never payloads; small cells (<5) suppressed in secondary breakdowns.
- **Audit events** store hashes + versions by default (`AUDIT_STORE_CONTENT=false`); chain each record to the previous (`prev_hash`); failing to write an audit record aborts the run.
- Never silence or loosen a guardrail to make a test pass; add the adversarial case to `tests/guardrails/` first.
- Prompts are versioned files; changing one requires re-running the grounding corpus.

## References (verified 2026-11-16)
- OWASP Top 10 for LLM applications — https://genai.owasp.org/llm-top-10/
- OWASP LLM prompt-injection prevention cheat sheet — https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
- LGPD — https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm
- Problem Details for HTTP APIs (RFC 9457) — https://www.rfc-editor.org/rfc/rfc9457
- OpenTelemetry GenAI semantic conventions — https://opentelemetry.io/docs/specs/semconv/gen-ai/
