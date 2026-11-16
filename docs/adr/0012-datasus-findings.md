# ADR 0012 — Achados do spike do dataset DATASUS (T0b)

- Status: aceito (2026-11-16) · Scripts: `spikes/t0b/profile_parquet.py`, `spikes/t0b/profile_dates.py` (imprimem apenas agregados)

## Achados
1. **API CKAN indisponível**: `/api/3/action/package_show` e `resource_show` respondem **404** no portal `dadosabertos.saude.gov.br`. A página do recurso expõe o link "Baixar" apontando para o S3 público `s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/<ano>/INFLUD<aa>-<dd>-<mm>-<aaaa>.parquet` (ex.: `…/2026/INFLUD26-16-11-2026.parquet`). **O nome do arquivo muda a cada atualização semanal** (carrega a data), e a listagem do bucket retorna 403.
2. **Colunas confirmadas** (194 colunas nos arquivos 2025 e 2026, schema idêntico): todas as colunas da allowlist existem. Tipos: `DT_NOTIFIC`/`DT_SIN_PRI` = `Datetime` (já tipadas); `SG_UF_NOT`, `HOSPITAL`, `UTI`, `EVOLUCAO`, `VACINA_COV`, `VACINA` = `String` com códigos `"1"`, `"2"`, `"3"`, `"9"` e **`null`**; `CLASSI_FIN` = `Decimal`.
3. **Códigos observados** — `HOSPITAL`: 1, 2, 9, null (≈ 95–96 % = 1; `HOSPITAL=1` **não é redundante**: ≈ 4 % são 2/9/null); `UTI`: 1, 2, 9, null; `EVOLUCAO`: 1, 2, 3, 9, null (3 = óbito por outras causas confirmado); `VACINA_COV` e `VACINA`: 1, 2, 9 (+ poucos null). **`null` deve ser tratado como "ignorado"** nas regras de denominador.
4. **Particionamento por ano epidemiológico do início de sintomas**: o arquivo "2025" tem `DT_SIN_PRI` de 2024-12-29 a 2026-01-03 (SE 1–52/53 de 2025) e `DT_NOTIFIC` de 2024-12-29 a 2026-11-03; o "2026" começa em 2026-01-04. Logo o arquivo de um ano contém notificações tardias de meses seguintes, e uma série por `DT_NOTIFIC` precisa de **2025 + 2026** (ingerir o ano anterior ao menos).
5. **Qualidade das datas** (585 334 linhas em 2025+2026): sem `DT_NOTIFIC` nulo, sem datas futuras, sem `DT_NOTIFIC < DT_SIN_PRI`; defasagem notificação−sintomas: mediana 4 d, p75 7 d, 2,4 % > 30 d, 0,5 % > 90 d, máx. 600 d. Confirma a escolha de `DT_NOTIFIC` (ADR 0011) e a necessidade do aviso de maturidade; os dias mais recentes (e fins de semana) têm volume menor.
6. **Volume**: 2025 = 336 435 linhas; 2026 (até 15/11) = 248 899. Mensal recente (por `DT_NOTIFIC`): ≈ 16–31 mil/mês em 2026.
7. **Leitura remota com projeção funciona**: `polars.scan_parquet(<url https>)` com `select` das colunas da allowlist lê só esses blocos de coluna — as colunas identificáveis **nem chegam à máquina**. Download completo do arquivo não é necessário.
8. **Dicionário** (`…/SRAG/dicionario-de-dados-2019-a-2025.pdf`, 28 págs.): confirma "Recebeu vacina COVID-19? 1-Sim 2-Não 9-Ignorado" (`VACINA_COV`) e a natureza SIVEP-Gripe da base; o PDF não distingue facilmente nome de variável × descrição na extração — a validação final dos códigos foi feita nos dados.

## Decisões
- **Descoberta de URL**: ler a página do recurso (`/dataset/srag-2019-a-2026/resource/<id>`) e extrair o link "Baixar" por regex restrita ao host/prefixo S3 esperado (`https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/`), com os **IDs de recurso por ano** em configuração; permitir `--url` explícito como override; falhar de forma clara se o padrão mudar. Sem API CKAN.
- **Ingestão por leitura remota** com projeção (sem baixar o arquivo inteiro nem manter `data/raw`); o `--keep-raw` vira opcional/depuração. Registrar no manifest URL final, tamanho do corpo (quando disponível) e linhas lidas.
- **Allowlist reduzida a 8 colunas**: `DT_NOTIFIC`, `DT_SIN_PRI` (apenas para a métrica interna de defasagem/maturidade), `SG_UF_NOT`, `HOSPITAL`, `UTI`, `EVOLUCAO`, `VACINA_COV`, `VACINA`. `CLASSI_FIN` sai (não usada → minimização).
- **Anos ingeridos**: padrão = ano de `as_of` e o anterior; cobre a janela de 12 meses. Notificações com início de sintomas dois anos epidemiológicos atrás (arquivo mais antigo) ficam de fora — impacto desprezível (lag máx. observado 600 d, 0,5 % > 90 d); documentar no relatório como limitação e permitir `--years` adicional.
- **Regras de limpeza**: `null` e códigos fora do domínio → `9` (ignorado); `HOSPITAL ≠ 1` não entra nas métricas de gravidade (mas conta em `cases`).

## Consequências
- Specs 02 e 01, a skill `srag-datasus-ingest` e a tarefa T4 ajustadas.
- Risco residual: a regex do link "Baixar" depende do HTML do portal; coberto por teste com fixture da página e por falha explícita.
