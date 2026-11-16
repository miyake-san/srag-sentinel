# ADR 0014 — Achados do spike de notícias (GDELT) e PDF (WeasyPrint) — T0d

- Status: **aceito** (2026-11-16) — PDF e notícias; o usuário aprovou a cadeia **Google News RSS → GDELT** (com Tavily opcional)
- Scripts: `spikes/t0d/` (`gdelt_spike*.py`, `rss_spike.py`, `pdf_spike.py`, `run_pdf.sh`)

## PDF (WeasyPrint) — aceito ✔
- WeasyPrint **70.0** funciona em `python:3.14-slim` instalando apenas `libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core` (+ `pip install weasyprint`); sem compilador.
- PDF A4 de 1 página com SVG inline vetorial, `@page`/`@media print`, contador de páginas, acentuação correta (texto extraível), metadado `title` preenchido; ~12 KB.
- **API de fetcher mudou na v70:** `default_url_fetcher` não existe mais; usa-se a classe `URLFetcher` (`from weasyprint import URLFetcher`) e `HTML(string=…, url_fetcher=<objeto com fetch(url, headers=None)>)`. Um **fetcher que herda de `URLFetcher` e sobrescreve `fetch`** para registrar e recusar tudo **bloqueou as sondas SSRF (`http://169.254.169.254/…`) e LFI (`file:///etc/passwd`)** sem derrubar a renderização. (Um objeto que não herda de `URLFetcher` quebra por atributos internos.)

## GDELT DOC 2.0 — achados ⚠️
- **Limite documentado pelo serviço: 1 requisição a cada 5 s** (mensagem do HTTP 429, que é texto puro, não JSON).
- Na prática, a partir desta rede: **429 em 8 de 13 chamadas**, mesmo espaçando 8–20 s; **latência 11–19 s até nas respostas 429**; respostas 200 chegaram a vir **vazias (`{}`)**.
- **Baixa relevância:** consultas por `influenza`/`srag` com `sourcelang:portuguese` (30 d) retornaram **3 artigos, sem relação com saúde pública** (preços de pet shop/veterinária), idênticos entre consultas diferentes; a consulta com frases exatas e `OR` retornou vazio.
- Formato quando funciona: `{"articles":[{domain, language, seendate, socialimage, sourcecountry, title, url, url_mobile}]}`.
- Conclusão: **GDELT sozinho não sustenta o requisito "notícias em tempo real" com qualidade**; o relatório ficaria quase sempre degradado ou com notícias irrelevantes.

## Alternativa avaliada (sem chave): Google News RSS (pt-BR)
- `https://news.google.com/rss/search?q=<consulta>&hl=pt-BR&gl=BR&ceid=BR:pt-419` com operador `when:30d`.
- **1,0–1,3 s**, HTTP 200, **60–100 itens por consulta**, muito relevantes (Agência Brasil, G1, CNN Brasil, Fiocruz/InfoGripe, COSEMS/SP…), campos `title, link, pubDate, source, description, guid`.
- Ressalvas: o `link` é um redirecionamento do Google News (não resolvemos; só exibimos); o feed é destinado a uso não comercial / ToS do Google (aceitável para PoC, a registrar no README); sem SLA; parsing de XML deve usar parser seguro (`defusedxml`).

## Decisão (aprovada pelo usuário em 2026-11-16; substitui "GDELT como padrão")
1. Manter a porta `NewsProvider` e **cadeia de provedores**: **Google News RSS primário** → **GDELT secundário** (best-effort) → **Tavily opcional** (com chave). Alternativa mínima: manter GDELT como único padrão e aceitar relatórios frequentemente sem notícias.
2. Independentemente da escolha, o cliente GDELT precisa de: **limitador (≥ 6 s entre chamadas, 1 por vez)**, **timeout ≥ 45 s**, no máx. **2 consultas por relatório**, tratamento de 429/corpo não-JSON/`{}`, **cache** (TTL 6 h) e consulta **simples** (sem `OR` complexo/frases longas).
3. O filtro de relevância (G2) passa a ser **obrigatório**: dados mostram que o provedor pode devolver itens fora do tema.
4. Impacto: T7 (provedores) e G2 (domínios permitidos: Agência Brasil, gov.br, Fiocruz, G1, CNN Brasil etc.); `defusedxml` entra como dependência.
