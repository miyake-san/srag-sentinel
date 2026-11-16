"""T0d spike: WeasyPrint PDF with inline SVG chart, @media print CSS, metadata, locked-down URL fetcher."""

import sys

from pypdf import PdfReader
from weasyprint import HTML

try:
    from weasyprint import URLFetcher
except ImportError:  # location differs between releases
    from weasyprint.urls import URLFetcher

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 120" width="600" height="240" role="img">'
    "<title>Casos diarios</title>"
    '<rect x="10" y="60" width="20" height="50" fill="#1f77b4"/>'
    '<rect x="40" y="30" width="20" height="80" fill="#1f77b4"/>'
    '<text x="10" y="15" font-size="10">Casos notificados por dia (SVG vetorial)</text></svg>'
)
HTML_DOC = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório SRAG – teste</title>
<style>
@page {{ size: A4; margin: 18mm; @bottom-right {{ content: "Página " counter(page) " de " counter(pages); font-size: 9pt }} }}
body {{ font-family: sans-serif; font-size: 11pt }}
h1 {{ break-after: avoid }} .card {{ break-inside: avoid; border: 1px solid #999; padding: 6px }}
</style></head><body>
<h1>Relatório SRAG — acentuação: ação, vírus, hospitalização</h1>
<div class="card"><p>Taxa de mortalidade: 4,7 % (proxy não)</p></div>
{SVG}
<p><a href="https://example.org/noticia">Notícia exemplo</a></p>
<img src="http://169.254.169.254/latest/meta-data/" alt="ssrf probe">
<img src="file:///etc/passwd" alt="lfi probe">
</body></html>"""

blocked: list[str] = []


class LockedFetcher(URLFetcher):
    """WeasyPrint 70 fetcher object: reject every external resource (http/https/file)."""

    def fetch(self, url: str, headers: dict | None = None):
        blocked.append(url)
        raise ValueError(f"blocked resource: {url}")


HTML(string=HTML_DOC, url_fetcher=LockedFetcher()).write_pdf("/work/out.pdf", custom_metadata=True)
reader = PdfReader("/work/out.pdf")
text = reader.pages[0].extract_text()
print("pages:", len(reader.pages))
print("metadata title:", reader.metadata.title if reader.metadata else None)
print("text extractable:", "mortalidade" in text and "vírus" in text)
print("text sample:", text[:120].replace("\n", " | "))
print("blocked fetches:", blocked)
sys.exit(0 if len(reader.pages) >= 1 and blocked else 1)
