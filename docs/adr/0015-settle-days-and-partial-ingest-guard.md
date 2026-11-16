# ADR 0015 — Dias de assentamento (settle days) e guarda contra ingestão parcial

- Status: aceito (2026-11-16) · Origem: revisão da Fase 1

## Contexto
1. **Viés da M1.** Os dias mais recentes do banco estão sempre incompletos (defasagem de notificação com mediana ≈ 4 dias e 2,4 % > 30 dias — ADR 0012 — mais quedas de fim de semana). Na execução real de 2026-11-16, os dois últimos dias tinham 67 e 40 casos contra ≈ 500 em dias normais, e a M1 saía **−15,6 %**, em parte artefato.
2. **Ingestão parcial.** Cada arquivo anual do DATASUS é particionado pelo ano epidemiológico do início de sintomas e contém notificações tardias; um mesmo dia pode estar em dois arquivos. Ingerir só um arquivo sobrescreve o dia com contagem parcial.

## Decisão
1. **`settle_days` (padrão 3)**: quando `as_of` não é informado, ele passa a ser `último_dia_disponível − settle_days`. `as_of` explícito nunca é deslocado. Os dias excluídos são **declarados** no relatório (`data_maturity`). Parâmetro `0 ≤ settle_days ≤ 14` (CLI `--settle-days`). Vale para métricas **e** séries (mesmo `as_of`).
2. **`ingest` exige ≥ 2 arquivos anuais** (ano atual e anterior). Com menos, falha com erro explícito; `--allow-partial` aceita o risco (com aviso no log).

## Resultado medido (dados reais, 2026-11-16)
| | antes | depois |
|---|---|---|
| `as_of` | 2026-11-15 | 2026-11-12 |
| M1 (aumento de casos) | −15,6 % | **−8,8 %** |
| Completude de desfecho (M2) | 49,8 % (aviso) | 53,6 % |

## Consequências
- A narrativa e o relatório passam a citar a data efetiva (`as_of`) e a nota de exclusão.
- Alternativas descartadas: nowcasting estatístico (fora do escopo da PoC); excluir apenas fins de semana (não resolve a defasagem); usar início de sintomas (ADR 0011).
- `settle_days=3` é um padrão empírico baseado na mediana de defasagem; revisar se o perfil de notificação mudar.
