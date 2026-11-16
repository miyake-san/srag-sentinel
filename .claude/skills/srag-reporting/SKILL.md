---
name: srag-reporting
description: How srag-sentinel renders its report — matplotlib SVG charts (daily 30 days, monthly 12 months with partial-month marking), Jinja2 autoescaped HTML, JSON contract and WeasyPrint PDF with a locked-down URL fetcher. Use when editing src/srag_sentinel/reporting or report templates.
---

# srag-sentinel · Report rendering (HTML, JSON, PDF)

Spec: `docs/specs/02-data-and-metrics.md` §7 (charts) and `docs/specs/03-agent-and-tools.md` §5 (report contract).

## Rules
- Charts: matplotlib with the non-interactive `Agg`/SVG backend, no global pyplot state (use the object-oriented API and close figures). pt-BR titles/axes, `as_of` and data source in the footer, accessible palette, `<title>`/`<desc>` for screen readers. Daily chart: 30 days, zeros explicit, 7-day moving average. Monthly: 12 months, **current month visibly marked partial**.
- Same series feed the JSON and the charts (single source of truth); charts never recompute data.
- HTML: Jinja2 with autoescape **on**, inline CSS and inline SVG, no JavaScript, no remote assets, strict CSP. LLM text is data: escape it, never mark it safe.
- PDF: render **from the same HTML** with WeasyPrint and an `@media print` stylesheet (A4, page breaks, vector charts). Provide a custom fetcher that **subclasses `weasyprint.URLFetcher`** (WeasyPrint 70; `default_url_fetcher` no longer exists) and overrides `fetch(url, headers=None)` to record and refuse every `http(s)`/`file` URL (validated against SSRF/LFI probes in spike T0d; a fetcher not inheriting `URLFetcher` crashes). Docker needs `libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core`. A render failure becomes the `PDF_UNAVAILABLE` degradation, not a 500.
- Every artifact (HTML, JSON, PDF) carries the same provenance block and its SHA-256 goes into `report.json` and the audit record.
- Test with golden-file checks on stable parts (structure, metric values, labels), PDF smoke test (opens, page count > 0, text extractable), and an XSS test using a hostile news title.

## References (verified 2026-11-16)
- matplotlib — https://matplotlib.org/stable/
- Jinja2 — https://jinja.palletsprojects.com/
- WeasyPrint — https://doc.courtbouillon.org/weasyprint/stable/ (first steps: …/first_steps.html · API incl. URL fetchers: …/api_reference.html)
- For a polished PDF/document workflow in an interactive session, the generic `pdf` skill may help; the production path stays WeasyPrint.
