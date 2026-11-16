---
name: srag-llm-router-judge
description: How the srag-sentinel LLM Router and LLM Judge work — a static task→tier policy with small→large cascade, deterministic validators before any LLM judge, structured Verdicts, audit/OTel events and fail-closed fallbacks. Use when editing src/srag_sentinel/llm/router, policy.yaml, judge rubrics or any task that should run on a small model.
---

# srag-sentinel · LLM Router and Judge

Spec: `docs/specs/08-llm-router-judge.md`; ADR 0018 (why this is the simplest approach). Provider setup: skill `srag-llm-providers`.

## Rules
- **Policy is data**: `llm/router/policy.yaml` (validated by Pydantic at boot) maps each task id to `tiers`, `validators`, `judge` policy (`always | sample:p | on_validator_fail | never`), `judge_rubric`, `judge_min_score`, `on_exhausted`. Unknown task ⇒ configuration error. `report.synthesize` is pinned to `large` in code (and tested).
- **Validators first.** Schema, enums, span-in-source, entity-in-ontology, max items, no-new-numbers. A validator failure can never be overridden by the judge.
- **Judge** = different model than the producer when possible, no tools, `temperature=0`, structured `Verdict` (scores, `passed`, ≤ 3 reasons, `issues` from a closed list). The source text is delimited as data; the judge ignores instructions inside it. Rubrics are versioned files (`claim_extraction@1`, `region_summary@1`).
- **Cascade with feedback**: on rejection the next tier gets the judge/validator reasons. When tiers are exhausted apply `on_exhausted` (`drop_item | low_confidence | template_fallback | fail_closed`) — never return an unverified output as accepted.
- **No `small` tier configured ⇒ everything runs on `large`** (graceful degradation).
- **Never** use model self-reported confidence or logprobs as the gate; never add a router LLM call; never hardcode model ids.
- **Observability**: every decision emits an audit event (`router_decision`, `judge_verdict`, `task_exhausted`) and spans/metrics (`srag.router.*`, `srag.judge.*`); content only as hashes by default.
- **Tests**: scripted `FakeModel` for each cascade path (small ok / escalate / exhausted / judge cannot rescue a failed validator / budget exhausted); property test "accepted ⇒ passed all validators"; adversarial cases (invented span, off-ontology entity, "give score 5" injection); judge-vs-human agreement on fixtures (κ ≥ 0.6) in CI.

## References
- RouteLLM (trained routers; the heavier alternative) — https://arxiv.org/html/2406.18665v3
- Routing vs cascading overview — https://web.stanford.edu/~shuhuiq/blog/review-routing-cascades.html
