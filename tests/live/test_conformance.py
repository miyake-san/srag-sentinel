"""Live provider conformance: each configured provider must return a valid structured output.

Run with the provider's key exported, e.g.
    ANTHROPIC_API_KEY=... SRAG_LLM_PROVIDER=anthropic uv run pytest -m live
Skipped automatically when the active provider has no API key.
"""

import pytest
from pydantic import BaseModel

from srag_sentinel.llm.factory import LLMConfigError, build_large_model
from srag_sentinel.settings import Settings

pytestmark = pytest.mark.live


class Pong(BaseModel):
    answer: str


async def test_active_provider_returns_structured_output() -> None:
    try:
        model = build_large_model(Settings())
    except LLMConfigError as error:
        pytest.skip(str(error))

    result = await model.invoke_structured(
        Pong, system="Answer with the single word 'pong'.", user="ping"
    )

    assert result.answer.strip()
