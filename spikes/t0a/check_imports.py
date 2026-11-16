"""T0a spike: import every top-level dependency and print the installed version."""

import importlib
import importlib.metadata as md
import sys

MODULES = {
    "langgraph": "langgraph",
    "langchain": "langchain",
    "langchain_anthropic": "langchain-anthropic",
    "langchain_google_genai": "langchain-google-genai",
    "langchain_nvidia_ai_endpoints": "langchain-nvidia-ai-endpoints",
    "langchain_openrouter": "langchain-openrouter",
    "surrealdb": "surrealdb",
    "polars": "polars",
    "weasyprint": "weasyprint",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic_settings": "pydantic-settings",
    "opentelemetry.sdk.trace": "opentelemetry-sdk",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": "opentelemetry-exporter-otlp",
    "matplotlib": "matplotlib",
    "jinja2": "jinja2",
    "httpx": "httpx",
    "hypothesis": "hypothesis",
    "respx": "respx",
}

print(f"python {sys.version.split()[0]}")
failed = 0
for module, dist in MODULES.items():
    try:
        importlib.import_module(module)
        print(f"PASS {dist} {md.version(dist)}")
    except Exception as exc:  # noqa: BLE001 - spike reports every failure kind
        failed += 1
        print(f"FAIL {dist}: {type(exc).__name__}: {exc}")
sys.exit(1 if failed else 0)
