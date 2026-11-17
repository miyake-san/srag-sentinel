"""Live judge calibration against labelled items derived from the KG corpus.

Items: each corpus article with its gold claims (human decision: accept) and with one
deliberate corruption per article (wrong direction, wrong UF or invented span: reject).
Needs the ``judge`` tier configured (or the main model as fallback) and its API key.
    ANTHROPIC_API_KEY=... uv run pytest -m live tests/live/test_judge_calibration.py
"""

import json
from pathlib import Path

import pytest

from srag_sentinel.kg.claims import ClaimDraft, ClaimDraftList, article_text
from srag_sentinel.llm.factory import LLMConfigError, build_large_model
from srag_sentinel.llm.router.calibration import LabelledItem, measure_agreement
from srag_sentinel.llm.router.judge import LlmJudge
from srag_sentinel.settings import Settings

pytestmark = pytest.mark.live
CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "kg" / "corpus.json"
FLIP = {"up": "down", "down": "up", "stable": "up", "unknown": "up"}


def _draft(
    claim: dict[str, object], *, direction: str | None = None, span: str | None = None
) -> ClaimDraft:
    return ClaimDraft(
        type=claim["type"],  # type: ignore[arg-type]
        text="paráfrase",
        evidence_span=span or str(claim["span"]),
        uf_codes=tuple(claim["ufs"]),  # type: ignore[arg-type]
        pathogen_ids=tuple(claim["pathogens"]),  # type: ignore[arg-type]
        direction=direction or str(claim["direction"]),  # type: ignore[arg-type]
    )


def _items() -> list[LabelledItem]:
    items: list[LabelledItem] = []
    for entry in json.loads(CORPUS.read_text(encoding="utf-8")):
        if not entry["claims"]:
            continue
        source = article_text(entry["title"], entry["snippet"])
        gold = ClaimDraftList(claims=tuple(_draft(c) for c in entry["claims"]))
        items.append(LabelledItem(f"{entry['id']}-gold", source, gold, human_pass=True))
        first = entry["claims"][0]
        corrupted = ClaimDraftList(claims=(_draft(first, direction=FLIP[first["direction"]]),))
        items.append(LabelledItem(f"{entry['id']}-flip", source, corrupted, human_pass=False))
    return items


async def test_judge_agrees_with_the_labels() -> None:
    try:
        judge = LlmJudge(build_large_model(Settings()))
    except LLMConfigError as error:
        pytest.skip(str(error))

    result = await measure_agreement(judge, "claim_extraction@1", _items())

    print(result)
    assert result.false_accepts == 0
    assert result.meets_target, result
