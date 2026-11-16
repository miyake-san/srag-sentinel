"""Build the three report artifacts (HTML, JSON, PDF) from a draft and write them to disk."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from srag_sentinel.agent.report import ReportDraft
from srag_sentinel.reporting.pdf import PDF_UNAVAILABLE, PdfUnavailableError, render_pdf
from srag_sentinel.reporting.render import render_html, render_json, sha256_hex

PdfRenderer = Callable[[str], bytes]


@dataclass(frozen=True)
class ReportBundle:
    """The rendered artifacts. ``pdf`` is ``None`` when it was unavailable (see ``draft``)."""

    draft: ReportDraft
    html: str
    json: str
    pdf: bytes | None

    @property
    def hashes(self) -> dict[str, str]:
        """SHA-256 of every artifact that exists (what the audit trail records)."""
        found = {"html_sha256": sha256_hex(self.html.encode("utf-8")), "json_sha256": ""}
        found["json_sha256"] = sha256_hex(self.json.encode("utf-8"))
        if self.pdf is not None:
            found["pdf_sha256"] = sha256_hex(self.pdf)
        return found


def build_bundle(draft: ReportDraft, *, pdf_renderer: PdfRenderer = render_pdf) -> ReportBundle:
    """Render HTML, then the PDF from that same HTML, then ``report.json`` with both hashes.

    A PDF failure degrades the report instead of failing it: the draft gains ``PDF_UNAVAILABLE``
    and the HTML is rendered again so it tells the reader.
    """
    html = render_html(draft)
    try:
        pdf: bytes | None = pdf_renderer(html)
    except PdfUnavailableError:
        pdf = None
        draft = draft.model_copy(
            update={
                "status": "degraded",
                "degradations": (*draft.degradations, PDF_UNAVAILABLE),
            }
        )
        html = render_html(draft)
    return ReportBundle(
        draft=draft, html=html, json=render_json(draft, html=html, pdf=pdf), pdf=pdf
    )


def write_bundle(bundle: ReportBundle, directory: Path) -> dict[str, Path]:
    """Write ``report.html``, ``report.json`` and (when available) ``report.pdf``."""
    directory.mkdir(parents=True, exist_ok=True)
    written = {
        "html": directory / "report.html",
        "json": directory / "report.json",
    }
    written["html"].write_text(bundle.html, encoding="utf-8")
    written["json"].write_text(bundle.json, encoding="utf-8")
    if bundle.pdf is not None:
        written["pdf"] = directory / "report.pdf"
        written["pdf"].write_bytes(bundle.pdf)
    return written
