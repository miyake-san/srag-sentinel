# ADR 0008 — Versão do Python: 3.14 (3.15 adiado)

- Status: aceito (T0a, 2026-11-16)

## Contexto
O pedido era usar a versão mais atual do Python. Em 2026-11-16 a série estável mais recente é 3.15 (3.15.2); 3.14 está em *bugfix*. A spec previa 3.15 com fallback para 3.14.

## Evidência (spike `spikes/t0a`)
- `uv sync --python 3.15` falhou: **`zstandard 0.25.0`** (puxado por `langgraph → langchain-core → langsmith`) não tem wheel cp315 e tentou compilar (exige Visual Studio no Windows); `pyyaml 6.0.3` também caiu para build de sdist.
- Em Linux, `pip install --only-binary=:all: zstandard==0.25.0` na imagem `python:3.15-slim` falha ("no matching distribution") — o problema não é só do Windows.
- `uv sync --python 3.14` resolveu 125 pacotes e instalou sem compilar nada; todos os imports passaram (langgraph 1.2.22, langchain 1.5.0, provedores Anthropic/Google/NVIDIA/OpenRouter, surrealdb 3.0.0, polars 2.1.0, fastapi 0.163.1, opentelemetry-sdk 1.45.2, matplotlib 3.11.2, jinja2, httpx, respx, hypothesis).
- WeasyPrint 70.0 instala mas, no Windows nativo, não acha `libgobject` (esperado; validação no Docker em T0d).
- Imagens `python:3.14-slim` (3.14.10) e `python:3.15-slim` (3.15.2) existem.

## Decisão
Usar **Python 3.14** (`requires-python = ">=3.14"`, imagem `python:3.14-slim`, `uv` com `.python-version` = 3.14). Reavaliar 3.15 quando `zstandard` e `pyyaml` publicarem wheels cp315 (ou quando `langsmith` deixar de exigir `zstandard`).

## Consequências
- Imagens e CI sem toolchain de compilação (menor superfície, build rápido).
- Ainda é a versão mais recente com ecossistema completo; migração para 3.15 deve ser uma troca de tag + `uv lock --upgrade` + CI verde.
- O SDK `surrealdb` 3.0.0 declara suporte até 3.14 — alinhado.

## Alternativas descartadas
- 3.15 com compilador na imagem: aumenta imagem/CI e fragilidade para ganho nulo.
- 3.13 ou anterior: contraria o pedido de versão atual sem necessidade.
