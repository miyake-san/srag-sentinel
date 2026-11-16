# ADR 0018 — LLM Router e LLM Judge: a forma mais simples de usar

- Status: aceito (2026-11-16) · Spec: [08](../specs/08-llm-router-judge.md)

## Contexto
As tarefas de GraphRAG (extrair afirmações de manchetes, classificar relevância, planejar consultas, resumir por região) são **estreitas, verificáveis e numerosas** — boas candidatas para LLMs pequenos. Queremos economia e latência menores **sem perder qualidade** e com decisões auditáveis (critério de governança do projeto). É preciso decidir **como** rotear e **como** julgar da forma mais simples que funcione.

## Opções para rotear
| Opção | Como funciona | Avaliação |
|---|---|---|
| **A. Tabela estática tarefa → camadas, com cascata e verificação** | cada tarefa declara `tiers: [small, large]`; tenta o menor, valida e escala se falhar | **mais simples**; zero treinamento; decisão explicável e testável |
| B. Roteador treinado (RouteLLM: matriz de fatoração, BERT, similaridade) | prevê, por consulta, se precisa do modelo forte; exige dados de preferência/treino | overkill: poucas tarefas fixas, nada para "prever" — a tarefa já define a dificuldade |
| C. Roteador por LLM ("pergunte a um LLM qual modelo usar") | uma chamada extra por tarefa | custo e latência extra; mais um ponto de falha e de injeção |
| D. Roteamento por embeddings/semântico | classifica a consulta por similaridade | desnecessário com tarefas tipadas; exige embeddings |
| E. Gateway "auto-router" de terceiros (ex.: auto-roteamento de provedores agregadores) | caixa-preta escolhe o modelo | perde controle/auditoria do modelo usado; conflita com governança |

## Opções para julgar
| Opção | Avaliação |
|---|---|
| **A. Validadores determinísticos primeiro; juiz LLM só em casos ambíguos/amostra** | **mais simples e barato**; checagens (schema, enums, span literal, entidade na ontologia) cobrem a maior parte dos erros reais |
| B. Juiz LLM em toda saída | dobra as chamadas; viés do juiz vira ponto único de falha |
| C. Confiança autodeclarada do modelo / logprobs | pouco calibrada (apontado na literatura/prática), limiar instável |
| D. Sem juiz | sem sinal de qualidade além do schema |

## Decisão
**Roteador = tabela estática por tarefa + cascata** (`small → large`) e **juiz = validadores determinísticos primeiro, juiz LLM (rubrica estruturada, preferencialmente outro modelo) apenas quando o validador reprova/está ambíguo ou por amostragem**. O juiz nunca aprova o que um validador reprovou; esgotadas as camadas, aplica-se `on_exhausted` (fail-closed por tarefa). A síntese final (`report.synthesize`) é fixa no tier `large` e verificada pelo G3 determinístico.

Implementação em código próprio (≈ uma pequena camada sobre a fábrica de provedores já existente): **nenhuma dependência nova**.

## Por que é a mais simples
- Um arquivo de política em YAML + um laço de cascata; nada a treinar, hospedar ou calibrar além de um limiar do juiz em fixtures.
- Os mesmos 4 provedores (Anthropic, Gemini, NVIDIA NIM, OpenRouter) servem a qualquer tier.
- Sem `small` configurado, tudo cai no `large` (degradação graciosa).

## Consequências
- A economia depende da taxa de aceitação no `small` (meta ≥ 70 % na extração); medir e ajustar a política com dados (`srag.router.escalations`).
- Evolução possível sem mudar contratos: trocar a política estática por um roteador aprendido ou por "tier médio", mantendo validadores e juiz.

## Referências (consultadas em 2026-11-16; blogs são fontes secundárias)
- RouteLLM — https://arxiv.org/html/2406.18665v3
- Roteamento por previsão × verificação (cascata) — https://web.stanford.edu/~shuhuiq/blog/review-routing-cascades.html
- Cascatas de modelos em produção — https://tianpan.co/blog/2025/11/03/llm-routing-model-cascades
