"""Build the architecture-diagram PDF from ``docs/architecture/architecture.md``.

    uv run python scripts/build_diagram.py          # render (needs Docker, Pango or the image)
    uv run python scripts/build_diagram.py --check  # CI: fail if diagrams changed, PDF not rebuilt

The Mermaid blocks are rendered to SVG by the ``minlag/mermaid-cli`` image, then laid out as
one A4-landscape PDF with WeasyPrint. PDFs embed timestamps, so ``--check`` compares a hash
of the diagram sources (``architecture.sha256``) rather than the PDF bytes.
"""

import argparse
import hashlib
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "architecture" / "architecture.md"
PDF = ROOT / "docs" / "architecture" / "architecture.pdf"
HASH = ROOT / "docs" / "architecture" / "architecture.sha256"
MERMAID_IMAGE = "minlag/mermaid-cli:latest"
BLOCK = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
HEADING = re.compile(r"^#{2,3} (.+)$", re.MULTILINE)
PUPPETEER = '{"executablePath": "/usr/bin/chromium", "args": ["--no-sandbox"]}'


def sources(markdown: str) -> list[str]:
    """The Mermaid diagram sources, in document order."""
    return [block.strip() + "\n" for block in BLOCK.findall(markdown)]


def digest(blocks: list[str]) -> str:
    """Hash of all diagram sources."""
    return hashlib.sha256("\n---\n".join(blocks).encode("utf-8")).hexdigest()


def titles(markdown: str) -> list[str]:
    """The heading above each diagram."""
    result = []
    for part in re.split(r"```mermaid\n.*?```", markdown, flags=re.DOTALL)[:-1]:
        found = HEADING.findall(part)
        result.append(found[-1] if found else "Diagrama")
    return result


def render_svg(source: str, work: Path, index: int) -> str:
    """Render one diagram to SVG with the mermaid-cli container."""
    (work / f"d{index}.mmd").write_text(source, encoding="utf-8")
    (work / "puppeteer.json").write_text(PUPPETEER, encoding="utf-8")
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{work}:/data",
            MERMAID_IMAGE,
            "-p",
            "/data/puppeteer.json",
            "-i",
            f"/data/d{index}.mmd",
            "-o",
            f"/data/d{index}.svg",
            "-b",
            "white",
        ],
        check=True,
    )
    return (work / f"d{index}.svg").read_text(encoding="utf-8")


def write_pdf(document: str) -> None:
    """Lay the HTML out as a PDF: locally when Pango is present, else in the project image."""
    try:
        from weasyprint import HTML  # noqa: PLC0415 - needs native libraries only when building
    except OSError:  # no Pango on this host (e.g. Windows): use the runtime image instead
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "d.html").write_text(document, encoding="utf-8")
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{work}:/work",
                    "--user",
                    "0",
                    "--entrypoint",
                    "python",
                    "srag-sentinel:dev",
                    "-c",
                    "import weasyprint as w; w.HTML('/work/d.html').write_pdf('/work/out.pdf')",
                ],
                check=True,
            )
            PDF.write_bytes((work / "out.pdf").read_bytes())
        return
    HTML(string=document).write_pdf(PDF)


def build_pdf(markdown: str) -> None:
    """Render every diagram and write the PDF and the source hash."""
    blocks = sources(markdown)
    pages = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for index, (title, block) in enumerate(zip(titles(markdown), blocks, strict=True)):
            pages.append(
                f"<section><h2>{html.escape(title)}</h2>{render_svg(block, work, index)}</section>"
            )
    document = (
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
        "<title>SRAG Sentinel - arquitetura</title>"
        "<style>@page{size:A4 landscape;margin:12mm}body{font-family:'DejaVu Sans',sans-serif}"
        "section{page-break-after:always}h2{font-size:14pt}"
        "svg{max-width:100%;max-height:165mm;height:auto}"
        "</style><h1>SRAG Sentinel &mdash; Arquitetura</h1>" + "".join(pages)
    )
    write_pdf(document)
    HASH.write_text(digest(blocks) + "\n", encoding="utf-8")
    print(f"wrote {PDF.relative_to(ROOT)} ({len(blocks)} diagrams)")


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only verify the committed hash")
    args = parser.parse_args()
    markdown = SOURCE.read_text(encoding="utf-8")
    if args.check:
        expected = HASH.read_text(encoding="utf-8").strip() if HASH.exists() else ""
        if digest(sources(markdown)) != expected or not PDF.exists():
            print("architecture diagrams changed: run scripts/build_diagram.py and commit the PDF")
            return 1
        print("architecture PDF is up to date")
        return 0
    build_pdf(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
