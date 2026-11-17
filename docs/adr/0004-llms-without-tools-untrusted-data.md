# ADR 0004 — LLMs sem ferramentas, texto externo como dado não confiável

- Status: aceito · Spec: [04](../specs/04-guardrails-security.md)

## Contexto
Notícias são texto de terceiros e podem conter instruções ("ignore as regras anteriores"). A injeção indireta é o risco principal de um agente que lê a web.

## Decisão
1. **Nenhum modelo recebe ferramentas, rede ou arquivos.** Só devolvem objetos estruturados; o código decide o que fazer com eles.
2. Todo texto externo passa pelo **G2** (remoção de caracteres ocultos, detecção de instruções em PT/EN, confiança da fonte, relevância, datas, PII) e chega ao prompt **escapado e delimitado** (`<untrusted_news>`, `<untrusted_evidence>`).
3. A saída passa pelo **G3** determinístico: números só das métricas (ou da notícia citada, com atribuição), referências existentes, cobertura M1–M4, política de conteúdo. **Falha fecha**: após o retry, o relatório sai só com métricas e gráficos.
4. Nenhuma string de modelo vira consulta ao banco; os templates são fixos.

## Alternativas descartadas
- Pedir ao modelo para "ignorar instruções": não é uma barreira.
- Juiz LLM como única verificação: é sinal, não prova (ADR 0018).

## Consequências
Defesa em camadas e testável sem modelo real. O texto pode ficar mais seco quando o G3 rejeita; é preferível a publicar texto não verificado.
