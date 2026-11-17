# syntax=docker/dockerfile:1
# SRAG Sentinel image: multi-stage, non-root, read-only-friendly. Python 3.14 (ADR 0008).

ARG PYTHON_IMAGE=python:3.14-slim

FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Optional LLM providers: "" (Anthropic only) or e.g. "--extra google --extra nvidia".
ARG LLM_EXTRAS=""
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project ${LLM_EXTRAS}
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev ${LLM_EXTRAS}

# The test stage runs the suite inside the container (CI): `docker build --target test .`
FROM builder AS test
COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen ${LLM_EXTRAS} && uv run pytest -q -p no:cacheprovider

FROM ${PYTHON_IMAGE} AS runtime
# WeasyPrint needs Pango; fonts for the PDF (validated in spike T0d).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 srag \
    && useradd --system --uid 10001 --gid srag --home-dir /nonexistent --shell /usr/sbin/nologin srag
# A named volume inherits this ownership on first use, so the non-root user can store reports.
RUN mkdir -p /data/reports && chown -R srag:srag /data
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/cache \
    SRAG_REPORTS_DIR=/data/reports
WORKDIR /app
COPY --from=builder --chown=srag:srag /app/.venv ./.venv
COPY --from=builder --chown=srag:srag /app/src ./src
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
ENTRYPOINT ["srag-sentinel"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
