# ADR 0009 — Formatos do relatório: HTML autocontido, JSON versionado e PDF do mesmo HTML

- Status: aceito · Spec: [03 §5](../specs/03-agent-and-tools.md) · Achados: [0014](0014-news-and-pdf-findings.md)

## Decisão
- **HTML** com Jinja2 (autoescape ligado), CSS e SVG inline, **sem JavaScript e sem recursos remotos**, com CSP restritiva. Texto de modelo e de notícia é sempre escapado; só links `http(s)` viram links.
- **JSON** (`schema_version` 1.0) com o mesmo conteúdo e os SHA-256 dos artefatos.
- **PDF** gerado pelo WeasyPrint **a partir do mesmo HTML**, com um buscador de URLs que só aceita `data:` (bloqueia SSRF e leitura de arquivos locais). Falha vira a degradação `PDF_UNAVAILABLE`, nunca erro 500.
- Gráficos em matplotlib (API orientada a objetos, SVG determinístico), alimentados pelas mesmas séries do JSON.

## Consequências
Uma única fonte de verdade para os três formatos. O WeasyPrint exige Pango: a imagem Docker traz as bibliotecas; em máquinas sem elas o PDF degrada e o teste de fumaça é pulado.
