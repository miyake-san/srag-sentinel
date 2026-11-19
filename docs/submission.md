# Relatório de entrega — SRAG Sentinel

**Repositório (público):** https://github.com/miyake-san/srag-sentinel

Desafio: Artificial Intelligence Engineer Certification (Indicium AI). A empresa do enunciado (HealthCare Co.) é fictícia.

## O que foi entregue

Um agente de IA generativa que consulta dados abertos de SRAG (OpenDATASUS) e notícias, e gera automaticamente um relatório (HTML, JSON e PDF) com uma narrativa verificada por código.

| Requisito do desafio | Onde está |
|---|---|
| Taxa de aumento de casos (M1) | `src/srag_sentinel/domain/`, README, seção de métricas |
| Taxa de mortalidade (M2) | idem |
| Taxa de ocupação de UTI (M3, **proxy**) | idem; o proxy é declarado no relatório |
| Taxa de vacinação da população (M4, **proxy**) | idem; o proxy é declarado no relatório |
| Gráfico: casos diários, últimos 30 dias | relatório (SVG determinístico, com média móvel de 7 dias) |
| Gráfico: casos mensais, últimos 12 meses | relatório (mês corrente parcial hachurado) |
| Notícias para contextualizar | Google News RSS + GDELT, filtradas pelo guardrail G2 |
| Diagrama de arquitetura conceitual (PDF) | [`docs/architecture/architecture.pdf`](architecture/architecture.pdf), fonte em [`architecture.md`](architecture/architecture.md) |
| Documentação no README | [`README.md`](../README.md) |

## Arquitetura (resumo)

- **Orquestrador:** LangGraph com fluxo fixo `validate → metrics → plan news → collect news → build KG → retrieve → synthesize → verify → render → finalize`. Os LLMs não têm ferramentas: só o código chama dados e notícias.
- **Ferramentas:** `get_srag_metrics`, `get_srag_series`, busca de notícias, busca no grafo de conhecimento.
- **LLM:** roteador small→large com juiz; provedores configuráveis (testado com Groq).
- **Banco:** SurrealDB (bases de dados agregados, app, auditoria encadeada por hash e grafo de conhecimento).
- **Observabilidade:** OpenTelemetry → Collector → Jaeger, Prometheus e Grafana.
- **Implantação:** Docker Compose, imagem não-root, CI no GitHub Actions.

## Governança, transparência e segurança

- **Auditoria:** trilha append-only com hash encadeado (`srag-sentinel audit verify|export`), com eventos por execução (decisões do roteador, vereditos do juiz, guardrails, hashes dos artefatos).
- **Guardrails:** G1 (entrada), G2 (notícias: sanitização, detecção de injeção, PII), G3 (a narrativa só pode citar números das métricas ou do artigo citado; falha fechada, gerando relatório só com métricas), G4 (orçamento de chamadas e prazo).
- **Dados sensíveis:** só 7 colunas permitidas são lidas da fonte; apenas agregados diários por UF são armazenados; nenhum dado individual chega a banco, logs ou traces. Depurador de PII (CPF/CNPJ, cartão, e-mail, telefone etc.).
- **Perímetro da API:** chaves Bearer, limite de taxa, limite de concorrência e de corpo, cabeçalhos de segurança.
- **Segredos:** `.env` fora do repositório; gitleaks e Trivy no CI.
- **Código limpo:** ruff e mypy em modo estrito; 721 testes passando (unidade, propriedades, adversariais e integração).

## Relatório de exemplo (real)

Gerado pelo stack Compose com dados, notícias e LLM reais: [`docs/example-report/`](example-report/README.md) (`report.pdf`, `report.html`, `report.json`). É **um** exemplo, não uma amostra estatística.

## Limitações declaradas

- UTI e vacinação são **proxies** dos dados abertos disponíveis, e o relatório os marca como tal.
- A narrativa pode ser rejeitada pelo G3 (3 de 4 execuções aceitas na amostra); nesse caso sai só com métricas e gráficos.
- Apenas o provedor Groq foi exercitado de ponta a ponta; o acordo do juiz com rótulos humanos (κ) é 0,59, abaixo da meta de 0,6.
- A latência de uma execução fica perto do prazo de 90 s (coleta de notícias domina).
- Custo e comparação com um analista humano não foram medidos. Detalhes em [`docs/evaluation.md`](evaluation.md) e [`docs/impact.md`](impact.md).

## Como executar

Veja o [`README.md`](../README.md) e o [`guia de uso`](usage-guide.md). Em resumo: configurar o `.env` (chaves e senhas), `docker compose up`, e `POST /v1/reports` com o cabeçalho `Authorization: Bearer`.
