# ADR 0022 — O detector de injeção é um sinal, não uma barreira

- Status: aceito (2026-11-17) · Spec: [09 §4](../specs/09-agent-and-api-security.md)

## Contexto
O G2 usa expressões regulares em texto sem acento e minúsculo ([`guardrails/news.py`](../../src/srag_sentinel/guardrails/news.py)). Uma sonda em 2026-11-17 mostrou o que ele pega (PT/EN/ES diretos, Unicode oculto depois da sanitização) e o que não pega (homóglifos cirílicos, francês, letras separadas, leetspeak, base64). Isso é inerente a detectores por padrão.

## Decisão
1. O detector **reduz ruído e gera auditoria**; nenhuma garantia de segurança pode depender dele.
2. A barreira é **estrutural**: modelos sem ferramentas, saída tipada, escape e delimitação, G3 determinístico, validadores e juiz que não desfaz erro de validador, quarentena e fail-closed.
3. Endurecer a normalização (NFKC, homóglifos comuns, letras isoladas) e ampliar idiomas só quando o custo de falso positivo for medido no corpus; cada evasão nova vira caso de teste, documentado como "detectado" ou "não detectado, contido por X".
4. Nunca anunciar o detector como proteção completa em README ou relatórios.

## Alternativas
- Classificador de injeção por LLM/modelo dedicado: sinal melhor, mas custo, latência e ele próprio é atacável; candidato futuro como segunda opinião, não substituto.
- Allowlist de texto (aceitar só frases conhecidas): inviável para notícias.

## Consequências
Uma injeção que escape ao detector pode influenciar texto **qualitativo** de uma afirmação citada, mas não números, referências, ferramentas nem consultas. Esse risco residual é declarado na [validação](../security-validation.md) e medido apenas quando houver modelo real.
