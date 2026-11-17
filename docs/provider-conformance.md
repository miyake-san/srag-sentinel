# Conformidade dos provedores de LLM

O sistema fala com os modelos por uma porta mínima (`StructuredModel`, ADR 0007). Este arquivo registra **o que foi de fato verificado**, sem estimativas.

| Provedor | Pacote | Chave | Teste `live` executado? | Resultado |
|---|---|---|---|---|
| Anthropic (padrão) | `langchain-anthropic` (já instalado) | `ANTHROPIC_API_KEY` | **não** (sem chave neste ambiente) | pendente |
| Google Gemini | extra `google` | `GOOGLE_API_KEY` / `GEMINI_API_KEY` | **não** | pendente |
| NVIDIA NIM | extra `nvidia` (+ `SRAG_NVIDIA_BASE_URL` se auto-hospedado) | `NVIDIA_API_KEY` | **não** | pendente |
| OpenRouter | extra `openrouter` | `OPENROUTER_API_KEY` | **não** | pendente |

## O que está verificado sem chave
- A fábrica falha cedo e com mensagem clara para provedor desconhecido, modelo vazio, chave ausente e pacote não instalado (testes unitários).
- Todo o fluxo roda com `ScriptedModel` (grafo, router, juiz, KG, relatório) e os 4 provedores importam por importação tardia.
- Na execução em contêiner com chave inválida, o relatório sai degradado como projetado, sem derrubar o serviço.

## O que ainda não foi verificado
- **Saída estruturada real por provedor.** Para a Anthropic foi adotado `method="json_schema"` porque o `langchain-anthropic` avisa que o tool calling forçado não é suportado no `claude-sonnet-5-5`; isso **não foi testado contra a API**. Os esquemas usam restrições (`min_length`, `max_length`, `Literal`) que cada provedor pode tratar de forma diferente.
- Qualidade da narrativa, taxa de aprovação do G3 com texto real, κ do juiz e F1 de afirmações (ver [`evaluation.md`](evaluation.md)).
- Latência p95 do relatório (meta ≤ 90 s) e custo por relatório com modelos reais.

## Como executar
```bash
# um provedor por vez; o teste é pulado se faltar a chave
ANTHROPIC_API_KEY=... uv run pytest -m live tests/live
GOOGLE_API_KEY=...    SRAG_LLM_PROVIDER=google_genai SRAG_LLM_MODEL=<modelo> uv run --extra google pytest -m live tests/live/test_conformance.py
```
Depois registre aqui a data, o modelo e o resultado de cada provedor.
