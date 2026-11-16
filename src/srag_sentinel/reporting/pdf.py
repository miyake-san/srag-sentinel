"""PDF rendering from the same HTML, with WeasyPrint locked away from the network and disk.

WeasyPrint is imported lazily: it needs native libraries (Pango) that a development machine may
lack, and a missing PDF must degrade the report (``PDF_UNAVAILABLE``), never break it.
"""

from typing import Any

PDF_UNAVAILABLE = "PDF_UNAVAILABLE"


class PdfUnavailableError(RuntimeError):
    """The PDF could not be produced (missing libraries or a rendering failure)."""


class BlockedResourceError(PermissionError):
    """The document tried to load an external resource."""


def check_resource(url: str) -> None:
    """Allow only ``data:`` URLs: the report is self-contained, so anything else is hostile."""
    if not url.lower().startswith("data:"):
        raise BlockedResourceError(f"external resource blocked: {url.split('?', 1)[0][:120]}")


def render_pdf(html: str, *, title: str = "Relatório SRAG") -> bytes:
    """Render ``html`` to a PDF (A4 comes from the stylesheet's ``@page``)."""
    try:
        from weasyprint import HTML, URLFetcher  # noqa: PLC0415 - optional native dependency
    except (ImportError, OSError) as error:  # OSError: Pango/GObject not found
        raise PdfUnavailableError("WeasyPrint is not available on this host") from error

    class LockedFetcher(URLFetcher):  # type: ignore[misc]
        """Records and refuses every non-``data:`` URL (SSRF and local file disclosure)."""

        blocked: list[str]

        def __init__(self) -> None:
            super().__init__()
            self.blocked = []

        def fetch(self, url: str, headers: Any = None) -> Any:
            try:
                check_resource(url)
            except BlockedResourceError:
                self.blocked.append(url)
                raise
            return super().fetch(url, headers)

    fetcher = LockedFetcher()
    try:
        document = HTML(string=html, url_fetcher=fetcher)
        rendered = document.render()
        rendered.metadata.title = title
        rendered.metadata.generator = "srag-sentinel"
        return bytes(rendered.write_pdf())
    except Exception as error:  # any renderer failure is a degradation, not a crash
        raise PdfUnavailableError(f"PDF rendering failed: {type(error).__name__}") from error
