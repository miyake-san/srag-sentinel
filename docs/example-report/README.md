# Relatório de exemplo

Relatório **real** gerado pelo stack Compose em 2026-11-18, escopo `BR`, janela de 30 dias, via `POST /v1/reports` autenticado.

| Item | Valor |
|---|---|
| Execução | `db8b13f7-ae08-4867-b99c-4a50a84f2b36` |
| Status | `ok`, sem degradações (narrativa aceita pelo G3, PDF gerado) |
| Dados | OpenDATASUS, 585.334 linhas ingeridas (agregados diários por UF) |
| Notícias | Google News RSS, filtradas pelo G2 (8 artigos aceitos) |
| Modelos | grande `groq:openai/gpt-oss-120b`, pequeno `groq:openai/gpt-oss-20b` |

Arquivos: [`report.pdf`](report.pdf), [`report.html`](report.html) (autocontido, sem JavaScript) e [`report.json`](report.json) (versionado, com hashes dos artefatos, modelos e prompts usados).

**Como ler:** é **um** exemplo, não uma amostra. Outras execuções com o mesmo modelo podem ter a narrativa rejeitada pelo G3 (3 de 4 foram aceitas) e sair só com métricas e gráficos. Os números de UTI e vacinação são **proxies** (ver o README). Os dados são agregados públicos; o arquivo não contém dados pessoais, e foi verificado por busca de e-mails, CPF, chaves e caminhos locais.
