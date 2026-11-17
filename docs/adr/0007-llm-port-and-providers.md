# ADR 0007 — Porta mínima de LLM e quatro provedores

- Status: aceito · Spec: [03 §4](../specs/03-agent-and-tools.md)

## Contexto
O projeto deve rodar com Anthropic (padrão), Gemini, NVIDIA NIM e OpenRouter, e ser testável sem chave.

## Decisão
O restante do código depende de uma porta `StructuredModel` (`invoke_structured(schema, system, user)`), que devolve um objeto Pydantic ou levanta `ModelError`. Uma fábrica com importação tardia constrói cada provedor via LangChain (extras opcionais), falha cedo com mensagem clara (modelo, chave, pacote) e usa `temperature=0` e **nenhuma ferramenta**. Nenhum id de modelo fica fixo no código além do padrão configurável. Para a Anthropic, a saída estruturada usa `method="json_schema"`, pois o tool calling forçado não é suportado nos modelos recentes. Um `ScriptedModel` determinístico serve a todos os testes.

## Alternativas descartadas
- Usar o SDK de cada provedor diretamente: quatro caminhos de código para manter.
- Depender de LangChain em todo o código: acopla os testes ao framework.

## Consequências
Trocar de provedor é configuração. O comportamento real de cada provedor só se confirma nos testes `live` (ver `docs/provider-conformance.md`).
