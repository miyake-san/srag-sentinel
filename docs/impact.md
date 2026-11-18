# Impacto da solução e como foi medido

> **Contexto fictício.** A "HealthCare Co." e o cenário de uso são inventados para este exercício. Os dados de saúde são reais e públicos (OpenDATASUS). Nada aqui descreve resultados em uma operação real.

Este documento separa três coisas: o que **foi medido** (e como), o que é **argumento qualitativo** e o que **não foi medido**. A seção final faz a revisão crítica da medição.

## 1. O impacto que a solução pretende gerar

Substituir a montagem manual do boletim de SRAG (extrair dados, calcular indicadores, procurar notícias, redigir) por um relatório **gerado automaticamente, verificável e auditável**, sem expor dados de pacientes. As dimensões de impacto, e se há medida para cada uma:

| Dimensão | Pergunta | Há medida? |
|---|---|---|
| Privacidade | quanto dado sensível deixa de ser lido e guardado? | **sim** |
| Velocidade da parte determinística | quanto custa calcular métricas, séries, gráficos e auditoria? | **sim** (sem LLM, notícias reais e PDF) |
| Transparência | dá para reconstituir e verificar o que foi feito? | **sim** (sobrecarga e verificação da trilha) |
| Segurança do texto gerado | o sistema resiste a injeção e não publica texto não verificado? | **parcial** (testes, não uso real) |
| Tempo do analista | quanto tempo se economiza? | **não** |
| Custo por relatório | quanto custa em modelos? | **não** |
| Qualidade e utilidade da narrativa | o texto ajuda a decidir? | **não** |

## 2. Resultados medidos

Medidos em 2026-11-17 com [`scripts/measure_impact.py`](../scripts/measure_impact.py); resultado bruto em [`impact-measurements.json`](impact-measurements.json).

| Indicador | Resultado |
|---|---|
| Colunas lidas do arquivo de origem | **7 de 194** (3,6%); as colunas identificáveis nunca chegam à máquina ([ADR 0002](adr/0002-datasus-column-allowlist-and-aggregates.md), [0012](adr/0012-datasus-findings.md)) |
| Linhas lidas → linhas guardadas | **585.334 → 17.944** contadores diários por UF (redução de **32,6×**); nenhuma linha de paciente é armazenada |
| Ingestão (2 arquivos anuais, leitura remota) | 12,4 s |
| Métricas + séries, Brasil | p50 0,137 s · p95 0,207 s (n = 20) |
| Métricas + séries, SP | p50 0,089 s · p95 0,111 s (n = 20) |
| Relatório completo **sem LLM** (grafo inteiro, gráficos, HTML e JSON, auditoria) | p50 1,18 s · p95 1,30 s · máx. 1,89 s (n = 20) |
| Tamanho dos artefatos | HTML 47,7 kB · JSON 9,1 kB (o PDF não foi gerado nessa máquina) |
| Auditoria | 26 eventos por execução; leitura e verificação de 520 eventos em 0,069 s; cadeia íntegra |

Medidas de segurança (nos testes, [`docs/evaluation.md`](evaluation.md)): 35 de 35 payloads de injeção detectados (após corrigir 13 lacunas que a primeira versão deixava passar), 0 afirmações envenenadas gravadas no grafo, 0 falsos positivos em 30 manchetes reais e relatório sem texto (nunca com texto não verificado) quando o G3 reprova.

## 3. Como foi medido

**Procedimento** (reproduzível com um comando):
```bash
SURREAL_ROOT_PASSWORD=<senha-descartavel> uv run python scripts/measure_impact.py --runs 20 --json docs/impact-measurements.json
```
1. Cria um namespace descartável no SurrealDB (removido ao final) e roda `db init`.
2. Ingere os arquivos reais do OpenDATASUS de 2025 e 2026 (leitura remota das 7 colunas permitidas) e cronometra. Conta as linhas lidas (manifesto da ingestão) e as linhas guardadas (`SELECT count()` em `srag_daily`).
3. Cronometra 20 execuções de métricas + séries para `BR` e `SP`, com o usuário de leitura da API.
4. Cronometra 20 execuções do relatório completo pelo `ReportService`, com **um modelo que sempre falha** (exercita todo o grafo menos o LLM) e **notícias vazias** (sem rede). Cada relatório sai degradado de propósito.
5. Lê os eventos de auditoria, conta os da última execução e verifica a cadeia.

**Ambiente:** máquina de desenvolvimento Windows, SurrealDB v4.0.1 em contêiner local, Python 3.14. Sem Pango, portanto **sem PDF** nestas medições (o PDF real foi gerado depois, pelo Compose: ver [`evaluation.md`](evaluation.md)).

## 4. O que não foi medido, e por quê

- **Tempo economizado pelo analista.** Exigiria medir o processo manual real. Qualquer número aqui seria inventado. *Como medir:* estudo de tempo e movimento, com 3 a 5 analistas montando o mesmo boletim à mão, contra o tempo de revisar o relatório gerado.
- **Latência e custo com LLM.** A latência do caminho completo foi **observada** em poucas execuções reais (Groq, pelo Compose): 63 s a 90 s por relatório, dominada pela busca de notícias (~50 s). Não há p95 estatístico (a meta era p95 ≤ 90 s, e a margem é estreita) e **o custo não foi medido** (não há telemetria de tokens nem de preço). A chave que foi colada na conversa não foi usada por política de segurança; as execuções reais usaram uma chave do próprio `.env` do usuário.
- **Qualidade da narrativa** (revisão humana), **κ do juiz** e **F1 de afirmações**: ver [`evaluation.md`](evaluation.md).

## 5. Revisão crítica: a medição faz sentido?

**Faz sentido para o que afirma, mas não sustenta uma afirmação de impacto de negócio.** Pontos:

1. **O que a medição prova.** Que a parte determinística é barata e previsível (≈1 s e < 0,3 s para as métricas), que o desenho minimiza dados (7 de 194 colunas, 32,6× menos linhas) e que a trilha de auditoria tem sobrecarga desprezível (26 eventos, 69 ms para verificar 520). Esses números são verdadeiros e reproduzíveis.
2. **A latência de 1,2 s é só sobrecarga de orquestração.** Não é o tempo "de ponta a ponta": exclui o LLM (que tende a dominar, na casa de segundos a dezenas de segundos), notícias reais (GDELT tem tempo limite de 45 s), o PDF e o grafo com extração real. Quem ler "1,2 s" como "o relatório sai em 1,2 s" estará errado; por isso aparece sempre com "sem LLM".
3. **Os relatórios medidos são degradados.** O caminho de falha do modelo é mais curto que o caminho feliz (sem síntese, sem retry do G3). O tempo do caminho completo é maior, e não foi medido.
4. **Amostra e ambiente.** n = 20 em uma única máquina, com o banco local (sem latência de rede) e cache quente; p95 com 20 pontos é grosseiro. Servem como ordem de grandeza, não como SLO.
5. **A "redução de 32,6×" mede linhas, não risco.** O indicador de privacidade mais forte é 7 de 194 colunas e *quais* (sem identificadores). Agregar por dia e UF também tem limite: UFs pequenas em dias de baixa contagem poderiam permitir reidentificação por contagens muito baixas; **não há supressão de células pequenas**, e isso não foi avaliado.
6. **Os números de segurança vêm de um corpus escrito por mim**, depois de conhecer as regras (e a primeira versão falhou em 13 de 35). São evidência de que o código faz o especificado, não de robustez contra atacantes reais.
7. **Faltam as medidas que mais importam ao negócio** (tempo do analista, custo, utilidade). Sem elas, "impacto" aqui significa **qualidade de engenharia e controle de risco**, não ganho operacional comprovado. Os ganhos de produtividade são uma hipótese razoável, não um resultado.
8. **Ingestão de 12,4 s** depende de rede e do S3 público; não é garantia.

**Veredito:** a medição é adequada como *evidência de viabilidade técnica, de minimização de dados e de baixo custo de orquestração*. Para falar de impacto de negócio, é preciso (a) repetir o caminho feliz com um LLM real em muitas UFs e datas (hoje há só poucas execuções), (b) medir o processo manual de referência e (c) validar a qualidade do texto com especialistas. Esses três passos estão listados em [`evaluation.md`](evaluation.md) e na seção 4 acima.
