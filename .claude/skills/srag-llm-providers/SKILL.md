---
name: srag-llm-providers
description: How srag-sentinel selects and configures LLM providers (Anthropic default, Google Gemini, NVIDIA NIM, OpenRouter) through one explicit factory, env vars, structured-output conformance tests and egress rules. Use when adding/changing a provider, model setting, API key handling or the llm/ package.
---

# srag-sentinel · LLM providers

Spec: `docs/specs/03-agent-and-tools.md` §4 (registry table) and ADR 0007.

| `SRAG_LLM_PROVIDER` | Package / extra | Class | Key env var |
|---|---|---|---|
| `anthropic` (default) | `langchain-anthropic` | `init_chat_model("anthropic:<model>")` | `ANTHROPIC_API_KEY` |
| `google_genai` | `langchain-google-genai` / `google` | `ChatGoogleGenerativeAI` | `GOOGLE_API_KEY` (falls back to `GEMINI_API_KEY`) |
| `nvidia` | `langchain-nvidia-ai-endpoints` / `nvidia` | `ChatNVIDIA` (`base_url` for self-hosted NIM) | `NVIDIA_API_KEY` |
| `openrouter` | `langchain-openrouter` / `openrouter` | `ChatOpenRouter` (`vendor/model` ids) | `OPENROUTER_API_KEY` |

## Rules
- One factory: `llm/factory.py::build_chat_model(settings) -> BaseChatModel`. Lazy-import the provider package; raise a clear error naming the missing extra.
- `temperature=0`; no tools bound (the LLM nodes only produce structured output).
- Do **not** hardcode model ids except the Anthropic default. Examples live in `.env.example` and must be re-checked against the provider catalog before use.
- Fail fast at boot: provider known, model set, key present (`SecretStr`), structured output supported (NIM: not every model supports it — check the model list/capabilities).
- Only the **active** provider's key is injected into containers; keys never appear in logs, traces, audit records or reports.
- Conformance: one `@pytest.mark.live` test per provider asserting that `NewsPlan` and `Narrative` parse and validate. Everything else uses the fake LLM.
- OpenRouter/NIM forward prompts to third parties: prompts contain only public aggregates and public news (see `docs/specs/04-guardrails-security.md`).

## References (verified 2026-11-16)
- LangChain chat models — https://docs.langchain.com/oss/python/langchain/models
- Anthropic integration — https://docs.langchain.com/oss/python/integrations/chat/anthropic
- Google Gemini integration — https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai
- NVIDIA NIM / AI Endpoints integration — https://docs.langchain.com/oss/python/integrations/chat/nvidia_ai_endpoints
- OpenRouter integration — https://docs.langchain.com/oss/python/integrations/chat/openrouter
- Gemini API docs — https://ai.google.dev/gemini-api/docs
- NVIDIA API Catalog — https://build.nvidia.com/
- For Anthropic API specifics (models, caching, structured output) use the `claude-api` skill if available in the session.
