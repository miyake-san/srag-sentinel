# ADR 0010 — Telemetria alimentada pelos eventos de auditoria, sem conteúdo

- Status: aceito · Spec: [06](../specs/06-observability-deployment.md)

## Decisão
Uma fachada `Telemetry` (OpenTelemetry) cria os spans `report.run` e `agent.node` e registra as métricas `srag.*`. As métricas de router, juiz, guardrail, tools e KG vêm do **`AuditRecorder`**, por onde já passa todo evento: assim os atributos são exatamente os escalares da auditoria (contagens, ids, códigos) e **conteúdo nunca chega à telemetria**, o que um teste verifica. Exportação por OTLP/HTTP para o Collector, que ainda remove atributos que poderiam carregar corpo de requisição. Logs em JSON com `trace_id`. Sem SDK configurado, a API do OTel é no-op.

## Alternativas descartadas
- Instrumentar cada chamada à mão: duplica a lógica e abre espaço para vazar conteúdo.
- Capturar prompts e respostas nos spans: contraria a política de dados.

## Consequências
Fica pendente a telemetria por chamada de LLM (tokens e custo), que depende de dados que a porta mínima ainda não expõe.
