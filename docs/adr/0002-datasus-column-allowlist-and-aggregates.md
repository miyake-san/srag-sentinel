# ADR 0002 — Dados do OpenDATASUS: lista de colunas permitidas e só agregados

- Status: aceito · Spec: [02](../specs/02-data-and-metrics.md) · Achados: [0012](0012-datasus-findings.md)

## Contexto
A base SRAG é de notificações individuais e contém campos identificadores. O relatório precisa apenas de contagens por dia e UF.

## Decisão
Ler o Parquet remoto com Polars selecionando **somente 7 colunas** (lista fixa em código) e agregar em contadores diários por UF antes de qualquer escrita. **Nenhuma linha de paciente** é armazenada, registrada em log ou enviada a um modelo. O snapshot ingerido recebe hash e manifesto; a ingestão exige pelo menos dois arquivos anuais (ADR 0015).

## Alternativas descartadas
- Baixar o arquivo inteiro e filtrar depois: as colunas sensíveis passariam pelo disco/memória sem necessidade.
- Armazenar as linhas e agregar na consulta: aumenta a superfície de LGPD sem ganho para o relatório.

## Consequências
Privacidade por construção: o que não é lido não vaza. O custo é perder análises por faixa etária ou município, fora do escopo.
