# ADR 0011 — Eixo temporal por data de notificação e métricas aproximadas (proxy)

- Status: aceito · Spec: [02 §6](../specs/02-data-and-metrics.md) · Achados: [0012](0012-datasus-findings.md), [0015](0015-settle-days-and-partial-ingest-guard.md)

## Decisão
- O eixo é `DT_NOTIFIC` (notificação), não o início dos sintomas: o início dos sintomas é mais fiel, mas os últimos dias ficam artificialmente baixos por atraso de notificação e geram falsa queda.
- **M1** crescimento de casos e **M2** mortalidade entre hospitalizados com desfecho conhecido são calculadas diretamente.
- **M3** (uso de UTI) e **M4** (vacinação entre os casos, para COVID-19 e influenza) são **proxies** e vêm marcadas como tal no relatório: M3 não é ocupação de leitos e M4 não é cobertura vacinal da população. Cada métrica traz numerador, denominador e completude.
- Nenhum valor é preenchido silenciosamente com zero: sem denominador, a métrica é `n/d`.

## Consequências
O relatório é honesto sobre o que mede. Uma fonte externa de ocupação de leitos e de cobertura vacinal substituiria os proxies em uma versão futura.
