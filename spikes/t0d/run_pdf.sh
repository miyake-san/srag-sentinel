#!/bin/sh
# Runs inside python:3.14-slim: install minimal system libs for WeasyPrint, then run the PDF spike.
set -e
apt-get update -qq
apt-get install -y -qq --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core
pip install -q weasyprint pypdf
python -c "import weasyprint; print('weasyprint', weasyprint.__version__)"
python /work/pdf_spike.py
ls -l /work/out.pdf
