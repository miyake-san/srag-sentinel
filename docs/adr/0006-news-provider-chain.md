# ADR 0006 — Notícias: cadeia Google News RSS → GDELT

- Status: aceito · Achados: [0014](0014-news-and-pdf-findings.md)

## Contexto
O relatório precisa de notícias recentes em português sem chave obrigatória. O GDELT, testado em spike, limitou a taxa e trouxe resultados fora do tema.

## Decisão
Provedores atrás de uma porta `NewsProvider`, em **cadeia** (união com deduplicação por URL canônica e por título): Google News RSS primeiro, GDELT depois, Tavily opcional (adiado). RSS lido com `defusedxml` e **sem seguir redirecionamentos**; GDELT com limitador de 6 s e tempo limite de 45 s. Falha de um provedor é degradação (`NEWS_UNAVAILABLE` só se todos falham). Consultas são validadas (sem operadores do provedor) e cacheadas por TTL.

## Alternativas descartadas
- GDELT sozinho (instável); NewsAPI e similares (chave paga).

## Consequências
Funciona sem chave. Dependemos de feeds públicos sujeitos a mudança; por isso a degradação é explícita no relatório.
