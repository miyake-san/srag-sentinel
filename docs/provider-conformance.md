# Conformidade dos provedores de LLM

O sistema fala com os modelos por uma porta mínima (`StructuredModel`, ADR 0007). A camada `large` pode usar uma **lista de prioridade com failover** (`SRAG_LLM_PRIORITY`): o primeiro provedor utilizável atende, o próximo entra se ele falhar. Este arquivo registra **o que foi de fato verificado**, sem estimativas.

| Prioridade sugerida | Provedor | Pacote (extra) | Credencial / endpoint | Teste `live` executado? |
|---|---|---|---|---|
| 1 | OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | **não** |
| 2 | Groq | `groq` | `GROQ_API_KEY` | **sim** (2026-11-17, modelo configurado no `.env`): `test_conformance` passou; calibração do juiz em [`evaluation.md`](evaluation.md) |
| 3 | NVIDIA NIM | `nvidia` | `NVIDIA_API_KEY` (+ `SRAG_NVIDIA_BASE_URL` se auto-hospedado) | **não** |
| 4 | Unsloth / OpenAI-compatível | `unsloth` (`langchain-openai`) | `SRAG_UNSLOTH_BASE_URL` (obrigatório), `UNSLOTH_API_KEY` (opcional) | **não** |
| 5 | Gemini | `google` | `GOOGLE_API_KEY` / `GEMINI_API_KEY` | **não** |
| 6 | Ollama | `ollama` | `SRAG_OLLAMA_BASE_URL` (padrão `http://localhost:11434`), sem chave | **não** |
| — | Anthropic | incluído | `ANTHROPIC_API_KEY` | **não** (sem chave) |

## O que está verificado sem chave
- A fábrica monta cada um dos 7 provedores com as opções certas (chave, endpoint, temperatura 0, nenhuma ferramenta) e falha cedo com mensagem clara para provedor desconhecido, modelo vazio, chave ou endpoint ausente e pacote não instalado (testes unitários com classes de mentira).
- A cadeia respeita a ordem, **pula** provedores não configurados (sem expor segredos), cai para o próximo quando um falha e só falha se todos falharem (testes com `ScriptedModel`).
- Todo o fluxo do relatório roda com modelos simulados.

## O que ainda não foi verificado
- **Saída estruturada real por provedor.** Cada servidor trata esquemas e modos de forma diferente. O padrão é o do LangChain para cada classe; para a Anthropic usa-se `json_schema`. Servidores compatíveis com OpenAI (Unsloth, vLLM, llama.cpp) e modelos locais no Ollama variam muito: se falharem, tente `SRAG_LLM_STRUCTURED_METHOD=function_calling` ou `json_mode`. **Só o Groq foi testado contra um serviço real (2026-11-17): o padrão do LangChain (`function_calling`) falhou com `gpt-oss` e o padrão passou a `json_schema`; os demais provedores continuam sem teste real.**
- Modelos pequenos/locais podem não seguir o esquema com confiabilidade; nesse caso a cadeia passa ao próximo provedor e, se todos falharem, o relatório sai degradado (narrativa omitida), nunca com texto não verificado.
- Qualidade da narrativa, κ do juiz, F1 de afirmações, latência e custo (ver [`evaluation.md`](evaluation.md)).

## Como executar
```bash
# um provedor por vez; o teste é pulado se faltar credencial
GROQ_API_KEY=... SRAG_LLM_PRIORITY="groq=<modelo>" uv run --extra groq pytest -m live tests/live
SRAG_LLM_PRIORITY="ollama=<modelo>" uv run --extra ollama pytest -m live tests/live   # local, sem chave
```
Depois registre aqui a data, o modelo e o resultado de cada provedor.
