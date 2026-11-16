---
name: srag-langgraph
description: Project conventions for the LangGraph orchestrator in srag-sentinel (fixed-flow StateGraph, typed state, conditional retry edge, recursion/budget limits, per-node audit and OTel spans). Use when creating or changing the agent graph, nodes, state or edges. Complements the vendored `langchain-build-agent` skill.
---

# srag-sentinel · LangGraph orchestrator

Read first: `docs/specs/01-architecture.md` and `docs/specs/03-agent-and-tools.md`. The vendored `langchain-build-agent` skill says to use **LangGraph when explicit sequencing/branching is required** — that is this project (ADR 0001): a fixed-flow `StateGraph`, **not** a free ReAct/Deep Agent loop.

## Rules
- State is a Pydantic model (`ReportState`), serializable, no clients or secrets inside it. Nodes return partial updates only.
- Nodes are thin: they call ports (`MetricsRepository`, `NewsProvider`, `ChatModel`) injected via a factory, never concrete adapters or globals.
- The two LLM nodes (`plan_news_research`, `synthesize`) have **no tools** and return structured output (`with_structured_output` / Pydantic schema). Tool nodes are plain code.
- The only cycle is `verify_narrative → synthesize` (max 1 retry). Also set `recursion_limit` low and enforce the G4 budget in a wrapper.
- Every node is wrapped by one decorator that: opens an OTel span `node.<name>`, writes audit events (inputs/outputs **hashes**, duration, status), and converts exceptions into `Degradation` entries when the spec allows degrading.
- Degrade, don't crash: external failures (news, LLM, PDF) become `state.degradations`; only "no data" or audit failure aborts the run.
- Test the graph end to end with a **fake LLM** and `FakeNewsProvider`; also test each conditional edge and the fail-closed path (LLM that always lies ⇒ degraded report).

## References (verified 2026-11-16)
- LangGraph overview — https://docs.langchain.com/oss/python/langgraph/overview
- Graph API (state, nodes, edges, conditional edges) — https://docs.langchain.com/oss/python/langgraph/graph-api
- Persistence / checkpointers — https://docs.langchain.com/oss/python/langgraph/persistence
- Testing — https://docs.langchain.com/oss/python/langgraph/test
- Structured output — https://docs.langchain.com/oss/python/langchain/structured-output
- Doc index for lookups — https://docs.langchain.com/llms.txt

APIs move quickly: confirm signatures against the installed `langgraph` version (see `uv.lock`) before coding.
