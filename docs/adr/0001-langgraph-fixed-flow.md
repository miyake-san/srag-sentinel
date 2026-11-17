# ADR 0001 — Orquestração com LangGraph e fluxo fixo

- Status: aceito · Spec: [01](../specs/01-architecture.md), [03](../specs/03-agent-and-tools.md)

## Contexto
O relatório precisa de passos previsíveis (métricas, notícias, síntese, verificação) e de um caminho de falha definido. Um agente com laço livre de ferramentas é mais difícil de auditar, limitar em custo e proteger contra injeção.

## Decisão
`StateGraph` do LangGraph com **fluxo fixo**: `validate → fetch_metrics → plan_news → collect_news → build_kg → retrieve_context → synthesize → verify ⇄ synthesize (um retry) → render → finalize`. O único ciclo é verify→synthesize, no máximo uma vez, com o feedback do G3. Cada nó é auditado e instrumentado; o estado é só dado serializável (sem clientes nem segredos). `recursion_limit` baixo como segunda barreira.

## Alternativas descartadas
- **Agente ReAct com ferramentas livres:** a ordem das chamadas e o custo ficam imprevisíveis, e cada ferramenta vira superfície de injeção.
- **Cadeia linear sem grafo:** sem lugar natural para o retry condicional nem para as degradações.

## Consequências
Fluxo fácil de testar com modelos de mentira e de desenhar. Perde-se a flexibilidade de o modelo "decidir" buscar mais; para a PoC isso é intencional.
