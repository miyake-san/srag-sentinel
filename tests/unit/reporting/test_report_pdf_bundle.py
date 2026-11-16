import io
import json
from pathlib import Path

import pytest
from conftest import make_article, make_draft, make_narrative
from pypdf import PdfReader

from srag_sentinel.agent.report import ReportDraft
from srag_sentinel.reporting.bundle import build_bundle, write_bundle
from srag_sentinel.reporting.pdf import (
    BlockedResourceError,
    PdfUnavailableError,
    check_resource,
    render_pdf,
)
from srag_sentinel.reporting.render import sha256_hex


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "https://evil.example/x.css",
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "ftp://host/x",
    ],
)
def test_every_non_data_url_is_blocked(url: str) -> None:
    with pytest.raises(BlockedResourceError):
        check_resource(url)


def test_data_urls_are_allowed() -> None:
    check_resource("data:image/svg+xml;base64,AAAA")


def _fake_pdf(_html: str) -> bytes:
    return b"%PDF-1.7 fake"


def _failing_pdf(_html: str) -> bytes:
    raise PdfUnavailableError("no pango")


def test_bundle_carries_the_pdf_hash_in_the_json(draft: ReportDraft) -> None:
    bundle = build_bundle(draft, pdf_renderer=_fake_pdf)

    document = json.loads(bundle.json)
    assert bundle.pdf == b"%PDF-1.7 fake"
    assert document["artifacts"]["pdf_sha256"] == sha256_hex(b"%PDF-1.7 fake")
    assert document["report"]["status"] == "ok"


def test_pdf_failure_degrades_the_report_instead_of_failing(draft: ReportDraft) -> None:
    bundle = build_bundle(draft, pdf_renderer=_failing_pdf)

    document = json.loads(bundle.json)
    assert bundle.pdf is None
    assert document["artifacts"]["pdf_sha256"] is None
    assert document["report"]["status"] == "degraded"
    assert "PDF_UNAVAILABLE" in document["report"]["degradations"]
    assert "O PDF não pôde ser gerado" in bundle.html


def test_write_bundle_writes_only_the_available_files(tmp_path: Path, draft: ReportDraft) -> None:
    without_pdf = write_bundle(build_bundle(draft, pdf_renderer=_failing_pdf), tmp_path / "a")
    with_pdf = write_bundle(build_bundle(draft, pdf_renderer=_fake_pdf), tmp_path / "b")

    assert set(without_pdf) == {"html", "json"}
    assert set(with_pdf) == {"html", "json", "pdf"}
    assert with_pdf["pdf"].read_bytes() == b"%PDF-1.7 fake"


def test_real_pdf_is_a_readable_a4_document_with_extractable_text() -> None:
    draft = make_draft(narrative=make_narrative(), articles=(make_article(),))
    try:
        pdf = render_pdf(build_bundle(draft, pdf_renderer=_fake_pdf).html)
    except PdfUnavailableError:
        pytest.skip("WeasyPrint native libraries (Pango) are not installed on this host")

    reader = PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) >= 1
    assert "SRAG" in text
    assert "-8,8%" in text
    box = reader.pages[0].mediabox
    assert round(float(box.width)) == 595  # A4 width in points
    assert round(float(box.height)) == 842
