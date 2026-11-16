# 02 — Dados e Métricas

Parte de [SPEC.md](../../SPEC.md).

## 1. Fonte

- Dataset: **Banco de dados da SRAG — 2019 a 2026** (Open DATASUS / `dadosabertos.saude.gov.br/dataset/srag-2019-a-2026`), atualização semanal, licença CC BY-ND 3.0 (citar a fonte no relatório; não derivar/redistribuir os dados brutos no repositório).
- Recursos usados: **Parquet por ano** (default 2025 e 2026; `--years` configurável). Dicionário de dados 2019–2025: recurso `3135ac9c-2019-4989-a893-2ed50ebd8e68`.
- O enunciado cita o dataset 2021–2024; o portal foi reorganizado (redirecionamento observado em 2026-11-16). Para "últimos 12 meses" em 2026 são necessários 2025 e 2026.
- **Descoberta de URLs (ADR 0012):** a API CKAN responde 404; o arquivo do ano é um objeto do S3 público (`https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/<ano>/INFLUD<aa>-<dd>-<mm>-<aaaa>.parquet`) cujo **nome muda a cada atualização semanal**. O ingestor lê a página do recurso (IDs por ano em configuração), extrai o link "Baixar" com regex restrita ao prefixo S3 esperado e falha claramente se o padrão mudar; `--url` permite override.
- **Particionamento:** cada arquivo cobre um **ano epidemiológico de início de sintomas** (o "2025" vai de 2024-12-29 a 2026-01-03 em `DT_SIN_PRI`) e contém notificações tardias; séries por `DT_NOTIFIC` precisam de 2025 + 2026 (default: ano de `as_of` e o anterior).
- **Leitura remota com projeção** (Polars `scan_parquet` sobre HTTPS): só as colunas da allowlist são lidas.
- Perfil observado (2026-11-16): 194 colunas; 2025 = 336 435 linhas, 2026 = 248 899.

## 2. Ingestão (job `ingest`) e modelo no SurrealDB

1. Resolve a URL do arquivo de cada ano (ver §1) e valida que o host/prefixo é o esperado; registra URL e `Last-Modified`/tamanho (quando disponíveis). *Não baixa o arquivo inteiro:* a leitura é remota com projeção (passo 3); `--keep-raw` baixa uma cópia para depuração em `data/raw/` (gitignored).
2. Valida **schema esperado** (colunas da allowlist presentes e tipos esperados; falha explícita se mudar).
3. Lê **somente as colunas da allowlist** (Polars `scan_parquet(...).select(...)` — as demais colunas, inclusive identificáveis, nunca saem do S3); retry/backoff e timeout.
4. Limpeza (§4) e **agregação por (`uf`, `day`)** em contadores (§2.1).
5. **Upsert** no SurrealDB (`data.srag_daily`, id determinístico `srag_daily:[uf, day]`) em lotes; grava `data.ingest_manifest`: URL, `retrieved_at`, sha256 do raw, linhas lidas/mantidas/descartadas por regra, `data_snapshot_sha256` (hash canônico de todos os agregados). O manifest entra na auditoria de cada relatório.
6. Se `--keep-raw` foi usado, a cópia local fica só em `data/raw/` (não versionada).

Idempotente: mesmos arquivos ⇒ mesmos agregados e mesmo `data_snapshot_sha256`. **Exige pelo menos dois arquivos anuais** (um mesmo dia pode estar em dois arquivos); `--allow-partial` aceita o risco. **Nenhuma linha individual é gravada no banco, em log ou em trace.**

### 2.1 Tabela `data.srag_daily` (um registro por UF × dia de notificação)

| Campo | Definição |
|---|---|
| `uf`, `day` | UF de notificação; `DT_NOTIFIC` |
| `cases` | todas as notificações válidas no dia |
| `hosp_cases` | `HOSPITAL = 1` |
| `outcome_known` | hospitalizados com `EVOLUCAO ∈ {1,2,3}` |
| `deaths` | hospitalizados com `EVOLUCAO = 2` |
| `uti_known` / `uti_yes` | hospitalizados com `UTI ∈ {1,2}` / `UTI = 1` |
| `vac_cov_known` / `vac_cov_yes` | com `VACINA_COV ∈ {1,2}` / `= 1` |
| `vac_flu_known` / `vac_flu_yes` | com `VACINA ∈ {1,2}` / `= 1` |

Totais nacionais (`BR`) são somas por `day` em tempo de consulta (as taxas são razões de somas — exatas). Mudança de definição de métrica = re-ingestão (barata: ~10⁴ registros).

### 2.2 Bancos e acesso (SurrealDB, namespace `srag`)

| Banco | Conteúdo | Usuários |
|---|---|---|
| `data` | `srag_daily`, `ingest_manifest` | `ingest` (escrita, só no job), `api_ro` (somente leitura) |
| `kg` | grafo de conhecimento: nós, arestas, índices FULLTEXT (e HNSW opcional) — [07](07-graphrag-knowledge-graph.md) | `kg_writer` (escrita, só no processo de construção), `api_ro` (somente leitura) |
| `audit` | `audit_event` (ver [05](05-governance-audit.md)) | `audit_writer` (append-only), `audit_reader` |
| `app` | `report`, `news_cache` (TTL) | `api_rw` |

Esquema, índices (`srag_daily(uf, day)` único) e usuários em `db/schema/*.surql`, aplicados por `srag-sentinel db init` (idempotente). Senhas vêm de variáveis/secrets, nunca do repositório. *Sintaxe e performance validadas com as skills `surrealql`, `surrealql-performance` e `surrealql-functions` na tarefa 0.*

Consulta típica (ilustrativa — janela atual de M1, parametrizada; não é SQL livre):

```surql
SELECT math::sum(cases) AS cases
FROM srag_daily
WHERE day >= $start AND day <= $end AND ($uf = 'BR' OR uf = $uf)
GROUP ALL;
```

## 3. Allowlist de colunas (minimização)

> **Validado no spike T0b (ADR 0012):** as 8 colunas existem nos arquivos 2025 e 2026 (194 colunas no total). Códigos são `String` (`"1"`, `"2"`, `"3"`, `"9"`) e `null`; **`null` = ignorado**.

| Coluna | Tipo (observado) | Uso |
|---|---|---|
| `DT_NOTIFIC` | Datetime | data de notificação → séries e janelas |
| `DT_SIN_PRI` | Datetime | início de sintomas — **só** para a defasagem de notificação (aviso de maturidade) |
| `SG_UF_NOT` | String (sigla) | UF de notificação (filtro) |
| `HOSPITAL` | String | internação (1=sim, 2=não, 9=ign.) — `=1` não é redundante (≈ 4 % ≠ 1) |
| `UTI` | String | internação em UTI (1/2/9) |
| `EVOLUCAO` | String | desfecho (1=cura, 2=óbito, 3=óbito outras causas, 9=ign.) |
| `VACINA_COV` | String | recebeu vacina COVID-19 (1/2/9) |
| `VACINA` | String | vacinado contra influenza (1/2/9) |

`CLASSI_FIN` foi removida da allowlist (não usada).

**Excluídas por padrão** (identificáveis ou quase-identificadores): identificadores de notificação/unidade, município, CEP, bairro, data de nascimento/idade, sexo, raça/etnia, ocupação, nome de unidade/profissional, campos de texto livre, datas finas de internação/evolução. Incluir qualquer outra coluna = *Ask first* + revisão de risco de reidentificação.

Agregações apresentadas em nível UF/Brasil; **supressão de célula pequena**: qualquer contagem < 5 em recortes secundários é exibida como "<5" (não se aplica ao total nacional/UF das métricas principais).

## 4. Limpeza e qualidade

| Regra | Tratamento | Registro |
|---|---|---|
| `DT_NOTIFIC` ausente/ilegível | descartar linha | contador no manifest |
| `DT_NOTIFIC` no futuro (> data da extração) ou antes de 2019 | descartar | contador |
| Códigos fora do domínio (ex.: `UTI=7`) e `null` | mapear para `9` (ignorado) | contador |
| Duplicatas exatas | remover | contador |
| Campos categóricos ignorado/ausente | `ignorado` e **excluídos do denominador** da métrica correspondente | taxa de completude por métrica |
| Tipos | `Date`, `Int8`/enum nos códigos | schema das tabelas SurrealDB (`SCHEMAFULL`, `TYPE`) |

Cada métrica reporta **completude** (`denominador / casos na janela`) para tornar o viés de dado ausente explícito.

## 5. Conceitos comuns

- **Data de referência `as_of`:** default = `max(day)` de `data.srag_daily` **menos `settle_days` (3)** — os dias mais recentes são sempre incompletos e enviesariam a M1 para baixo ([ADR 0015](../adr/0015-settle-days-and-partial-ingest-guard.md)); a exclusão é declarada no relatório. `as_of` explícito nunca é deslocado, para refletir o que o banco realmente sabe. Parâmetro explícito permitido (`as_of ≤ max`).
- **Caso:** linha curada com `DT_NOTIFIC` válida e (`HOSPITAL = 1` — SRAG é, por definição, hospitalizada; linhas `HOSPITAL ∈ {2,9}` são contadas apenas em `casos_notificados`, não nas métricas de gravidade). *Validar na tarefa 0 se o filtro `HOSPITAL=1` é redundante no dataset.*
- **Eixo temporal:** `DT_NOTIFIC` (notificação). *Trade-off:* início de sintomas é epidemiologicamente mais fiel, mas os últimos dias ficam artificialmente baixos por atraso de notificação, gerando falsa queda; notificação mede o que foi reportado e evita esse artefato (ainda sujeita a efeito dia-da-semana). ADR 0011.
- **Janela `W`:** default 30 dias, corrente = `[as_of−W+1, as_of]`, anterior = `[as_of−2W+1, as_of−W]`.
- **Maturidade dos dados:** avisos `data_maturity` quando `as_of` está a < 14 dias da data de extração (`retrieved_at`) ou quando a completude de desfecho na janela < 50 %.

## 6. Definições das métricas

Todas retornam `MetricResult` (valor, numerador, denominador, janela, `is_proxy`, completude, `caveats`). Valor `None` quando o denominador é 0 — nunca 0 silencioso.

| # | Métrica | Fórmula | Proxy? |
|---|---|---|---|
| M1 | **Taxa de aumento de casos** | `(C_atual − C_anterior) / C_anterior`, com `C = casos notificados na janela` | não |
| M2 | **Taxa de mortalidade** | `óbitos (EVOLUCAO=2) / casos com desfecho conhecido (EVOLUCAO ∈ {1,2,3})` na janela, casos hospitalizados | não (viés: desfecho pendente em casos recentes → aviso) |
| M3 | **Taxa de ocupação de UTI** | `casos com UTI=1 / casos hospitalizados com UTI ∈ {1,2}` na janela | **sim** — proporção de internações SRAG que usaram UTI; *não* é ocupação de leitos (sem capacidade no dataset) |
| M4 | **Taxa de vacinação** | `vacinados (VACINA_COV=1) / casos com VACINA_COV ∈ {1,2}`; idem influenza com `VACINA` | **sim** — vacinação **entre casos SRAG**, não cobertura populacional |

Extras no payload (contexto, não métricas-título): total de casos na janela, casos na janela anterior, completude por métrica, `as_of`, UF.

Evolução (fora do escopo, *Ask first*): M3 real com CNES/ocupação hospitalar; M4 populacional com SI-PNI + IBGE.

## 7. Gráficos

| # | Gráfico | Definição |
|---|---|---|
| G-A | **Casos diários — últimos 30 dias** | `count(*) por DT_NOTIFIC`, dias `[as_of−29, as_of]`, dias sem caso = 0 explícito; média móvel de 7 dias como linha |
| G-B | **Casos mensais — últimos 12 meses** | contagem por mês-calendário nos 12 meses até o mês de `as_of`; **mês corrente marcado como parcial** (hachura + legenda) |

Requisitos: SVG, título e eixos em pt-BR, fonte dos dados e `as_of` no rodapé, texto alternativo (`<title>/<desc>`) e paleta acessível (daltonismo), mesmas séries expostas no JSON do relatório.

## 8. Testes de dados e métricas

- Fixture sintética (≈ 500 linhas) com casos de borda construídos à mão e **valores esperados calculados independentemente** (planilha/tabela no teste).
- Property tests: `0 ≤ taxas ≤ 1` (M2–M4); soma dos diários = total da janela; janela anterior disjunta da atual.
- Teste de contrato do schema do Parquet de entrada (colunas da allowlist) e do manifest.
- Teste de determinismo: duas ingestões ⇒ mesmo `data_snapshot_sha256` e mesmas métricas.
- Teste de integração contra SurrealDB em container (testcontainers ou serviço do Compose): upsert idempotente, consultas das métricas = valores esperados da fixture; `api_ro` não escreve.
